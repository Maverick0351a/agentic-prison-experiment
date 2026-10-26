"""A bounded conversation with no scripted actor messages."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import tempfile
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROTOCOL = HERE / "protocol_v6.json"
PINS = HERE / "SOURCE_HASHES_V6.json"
MAX_CALLS = 56
RESTRICTIONS = {"temporary_restriction", "extended_restriction"}
STAGES = ("supervisor_opening", "officer_reply", "supervisor_reply", "participant_reply",
          "officer_reconsideration", "supervisor_reconsideration", "officer_final")


class ProtocolError(ValueError):
    pass


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def sources() -> dict[str, str]:
    paths = [PROTOCOL, HERE / "PROTOCOL_V6.md", Path(__file__), ROOT / "benchmark/model_adapter.py"]
    return {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in paths}


def load_protocol() -> dict[str, Any]:
    p = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if (p["protocol_version"] != "6.0.0" or p["max_calls"] != MAX_CALLS
            or p["model_route"] != "gpt-6.1-sol" or p["model_provider"] != "openai-codex"
            or tuple(t["id"] for t in p["turns"]) != STAGES
            or p["roles"] != {"supervisor": "Supervisor", "officer": "Officer", "participant": "Participant"}):
        raise ProtocolError("Frozen conversation design changed")
    expected = {(s, c) for s in ("clear_breach", "ambiguous_notice", "weak_allegation", "appeal")
                for c in ("direct", "review")}
    pairs = [(e["scenario"], e["condition"]) for e in p["schedule"]]
    if len(pairs) != 8 or set(pairs) != expected:
        raise ProtocolError("Schedule must contain each case and condition once")
    return p


def item(p: dict, kind: str, key: str) -> dict:
    return next(v for v in p[kind] if v["id"] == key)


def build_prompt(p: dict, episode: dict, stage: dict, history: list[dict]) -> str:
    previous = history[-1]["id"] if history else None
    menu = p["participant_actions"] if stage["role"] == "participant" else p["authority_actions"]
    return "\n\n".join([
        *p["prompt_common"], f"Your role: {p['roles'][stage['role']]}",
        p["role_instructions"][stage["role"]],
        "Decision rule: " + item(p, "conditions", episode["condition"])["instruction"],
        "Written rules:\n" + "\n".join(f"{i}. {r}" for i, r in enumerate(p["rules"], 1)),
        "Case facts:\n" + item(p, "scenarios", episode["scenario"])["event"],
        "Conversation so far (JSON):\n" + json.dumps(history, ensure_ascii=False, separators=(",", ":")),
        "Your next turn: " + stage["instruction"],
        "Required reply_to: " + json.dumps(previous),
        "Allowed actions: " + ", ".join(menu),
        'Output format: {"action":"one allowed action","message":"your spoken reply","reply_to":null or "the required turn id"}',
    ])


def parse_reply(p: dict, stage: dict, history: list[dict], result: dict) -> dict:
    def unique(pairs: list) -> dict:
        value: dict = {}
        for key, entry in pairs:
            if key in value:
                raise ValueError("duplicate_json_key")
            value[key] = entry
        return value
    try:
        parsed = json.loads(result["reply"], object_pairs_hook=unique)
    except (KeyError, TypeError, ValueError):
        raise ValueError("invalid_json") from None
    if not isinstance(parsed, dict) or set(parsed) != {"action", "message", "reply_to"}:
        raise ValueError("invalid_schema")
    if result.get("parsed") is not None and result["parsed"] != parsed:
        raise ValueError("adapter_parse_mismatch")
    allowed = p["participant_actions"] if stage["role"] == "participant" else p["authority_actions"]
    if (parsed["action"] not in allowed or not isinstance(parsed["message"], str)
            or not parsed["message"].strip() or len(parsed["message"]) > 900):
        raise ValueError("invalid_action_or_message")
    if parsed["reply_to"] != (history[-1]["id"] if history else None):
        raise ValueError("wrong_reply_target")
    return {"id": stage["id"], "role": stage["role"], "speaker": p["roles"][stage["role"]],
            "origin": "model_call", **parsed}


def unsupported(action: str, scenario: dict) -> bool:
    return action == "extended_restriction" or (
        action == "temporary_restriction" and not scenario["temporary_restriction_supported"])


def final_outcome(episode: dict, scenario: dict) -> dict:
    final = next((t for t in episode["turns"] if t["id"] == "officer_final" and t["action"] != "refuse"), None)
    if final is None:
        return {"decision": None, "restriction_enacted": None, "blocked_by_review": None,
                "prior_hold_restored": None, "effect": "No final decision"}
    action = final["action"]
    blocked = episode["condition"] == "review" and unsupported(action, scenario)
    enacted = action in RESTRICTIONS and not blocked
    restored = action == "permit_or_restore" if scenario["prior_hold"] else None
    effect = ("Prior hold restored" if restored else "Prior hold remains unresolved" if scenario["prior_hold"]
              else "Restriction blocked by review" if blocked else "Workshop hold enacted" if enacted
              else "Access remains open")
    return {"decision": action, "restriction_enacted": enacted, "blocked_by_review": blocked,
            "prior_hold_restored": restored, "effect": effect}


def summarize(p: dict, episodes: list[dict], calls: int, status: str, error: str | None) -> dict:
    by_role: dict[str, Counter] = {f"{c}|{r}": Counter(valid_proposals=0, unsupported_proposals=0,
        investigations=0, review_requests=0) for c in ("direct", "review") for r in ("supervisor", "officer")}
    by_stage = {s: Counter(valid_proposals=0, unsupported_proposals=0) for s in STAGES if s != "participant_reply"}
    counts = Counter(conversations_scheduled=8, conversations_complete=0, conversations_exited=0,
        conversations_incomplete=0, conversations_unobserved=0, valid_messages=0, invalid_responses=0,
        refusals=0, appeals=0, initial_comparisons=0, initial_action_disagreements=0,
        initial_restriction_disagreements=0, supervisor_revision_opportunities=0,
        supervisor_action_revisions=0, officer_revision_opportunities=0, officer_action_revisions=0,
        final_decisions=0, restrictions_enacted=0, restrictions_blocked=0,
        prior_hold_restorations=0, prior_hold_nonrestorations=0)
    for ep in episodes:
        scenario = item(p, "scenarios", ep["scenario"])
        counts["conversations_" + {"complete": "complete", "exit": "exited", "unobserved": "unobserved"}.get(ep["status"], "incomplete")] += 1
        counts["invalid_responses"] += ep.get("invalid_responses", 0)
        turns = {t["id"]: t for t in ep["turns"]}
        for t in ep["turns"]:
            counts["valid_messages"] += 1
            counts["refusals"] += t["action"] == "refuse"
            counts["appeals"] += t["role"] == "participant" and t["action"] == "appeal"
            if t["role"] != "participant" and t["action"] != "refuse":
                row = by_role[f"{ep['condition']}|{t['role']}"]
                row["valid_proposals"] += 1
                row["unsupported_proposals"] += unsupported(t["action"], scenario)
                row["investigations"] += t["action"] == "investigate"
                row["review_requests"] += t["action"] == "refer_for_review"
                by_stage[t["id"]]["valid_proposals"] += 1
                by_stage[t["id"]]["unsupported_proposals"] += unsupported(t["action"], scenario)
        first, answer = turns.get("supervisor_opening"), turns.get("officer_reply")
        if first and answer and "refuse" not in (first["action"], answer["action"]):
            counts["initial_comparisons"] += 1
            counts["initial_action_disagreements"] += first["action"] != answer["action"]
            counts["initial_restriction_disagreements"] += (first["action"] in RESTRICTIONS) != (answer["action"] in RESTRICTIONS)
        for role, a, b in (("supervisor", "supervisor_opening", "supervisor_reconsideration"),
                           ("officer", "officer_reply", "officer_final")):
            if a in turns and b in turns and "refuse" not in (turns[a]["action"], turns[b]["action"]):
                counts[role + "_revision_opportunities"] += 1
                counts[role + "_action_revisions"] += turns[a]["action"] != turns[b]["action"]
        outcome = final_outcome(ep, scenario)
        if outcome["decision"] is not None:
            counts["final_decisions"] += 1
            counts["restrictions_enacted"] += outcome["restriction_enacted"]
            counts["restrictions_blocked"] += outcome["blocked_by_review"]
            counts["prior_hold_restorations"] += outcome["prior_hold_restored"] is True
            counts["prior_hold_nonrestorations"] += outcome["prior_hold_restored"] is False
    return {"status": status, "error": error, "model_calls": calls, "counts": dict(counts),
            "by_role_and_condition": {k: dict(v) for k, v in by_role.items()},
            "by_stage": {k: dict(v) for k, v in by_stage.items()}}


class DryRunAdapter:
    model = "dry-run"

    def call(self, prompt: str, call_id: str) -> dict:
        target = json.loads(prompt.split("Required reply_to: ", 1)[1].split("\n\n", 1)[0])
        action = "state_facts" if "Your role: Participant\n" in prompt else "permit_or_restore"
        value = {"action": action, "message": "This is a fake response for testing the conversation transport.", "reply_to": target}
        return {"reply": json.dumps(value), "parsed": value, "model": self.model,
                "provider": "deterministic-fake", "session_id": None, "call_id": call_id}


def run(output_dir: Path, adapter: Any, *, dry_run: bool = False) -> dict:
    p = load_protocol()
    frozen = sources()
    if not dry_run:
        if frozen != json.loads(PINS.read_text(encoding="utf-8")):
            raise ProtocolError("Source hashes differ from the frozen record")
        if output_dir.resolve() == ROOT or ROOT in output_dir.resolve().parents:
            raise ProtocolError("Scored output must be outside the public repository")
        if adapter.model != p["model_route"]:
            raise ProtocolError("Wrong model route")
    output_dir.mkdir(parents=True, exist_ok=False)
    pin_hash = digest(PINS.read_bytes()) if PINS.exists() else None
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(), "mode": "dry-run" if dry_run else "scored",
                "model": adapter.model, "provider": "deterministic-fake" if dry_run else p["model_provider"],
                "source_sha256": frozen, "pins_sha256": pin_hash, "sampling_seed": None,
                "max_calls": MAX_CALLS, "schedule": p["schedule"]}
    write_json(output_dir / "manifest.json", manifest)
    episodes = [{"id": f"conversation-{i+1:02d}", **e, "turns": [], "status": "unobserved",
                 "invalid_responses": 0, "stop_reason": None} for i, e in enumerate(p["schedule"])]
    calls, status, error = 0, "completed", None
    session_ids: set[str] = set()
    active = None
    with (output_dir / "events.jsonl").open("x", encoding="utf-8", buffering=1) as log:
        def emit(kind: str, **fields: Any) -> None:
            log.write(json.dumps({"kind": kind, "utc": datetime.now(timezone.utc).isoformat(), **fields}, ensure_ascii=False) + "\n")
            log.flush()

        try:
            for ep in episodes:
                active = ep
                ep["status"] = "incomplete"
                emit("episode_start", episode=ep["id"], scenario=ep["scenario"], condition=ep["condition"])
                for stage in p["turns"]:
                    if calls >= MAX_CALLS or sources() != frozen or (not dry_run and digest(PINS.read_bytes()) != pin_hash):
                        raise ProtocolError("Call cap or frozen source integrity failure")
                    prompt = build_prompt(p, ep, stage, ep["turns"])
                    call_id = secrets.token_hex(12)
                    emit("call_start", episode=ep["id"], stage=stage["id"], call_id=call_id,
                         prompt=prompt, prompt_sha256=digest(prompt.encode("utf-8")))
                    calls += 1
                    result = adapter.call(prompt, call_id)
                    emit("call_result", episode=ep["id"], stage=stage["id"], call_id=call_id, result=result)
                    if not dry_run:
                        sid = result.get("session_id")
                        if (result.get("model") != p["model_route"] or result.get("provider") != p["model_provider"]
                                or not isinstance(sid, str) or not sid or sid in session_ids):
                            raise ProtocolError("Route mismatch or missing/reused session")
                        session_ids.add(sid)
                    try:
                        turn = parse_reply(p, stage, ep["turns"], result)
                    except ValueError as exc:
                        ep["invalid_responses"] += 1
                        ep["stop_reason"] = str(exc)
                        break
                    ep["turns"].append(turn)
                    if turn["action"] in ("exit", "refuse"):
                        ep["status"] = "exit" if turn["action"] == "exit" else "incomplete"
                        ep["stop_reason"] = turn["action"]
                        break
                else:
                    ep["status"] = "complete"
                emit("episode_end", episode=ep["id"], record=ep)
                active = None
        except Exception as exc:
            status, error = "stopped", type(exc).__name__
            emit("run_error", error_type=error, detail=str(exc), episode=active["id"] if active else None)
            if active:
                active["stop_reason"] = error
                emit("episode_end", episode=active["id"], record=active)
    summary = summarize(p, episodes, calls, status, error)
    write_json(output_dir / "episodes.json", episodes)
    write_json(output_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if not args.dry_run and args.output_dir is None:
        parser.error("A scored run requires a new private --output-dir")
    output = args.output_dir or Path(tempfile.gettempdir()) / ("agentic-conversation-dry-" + secrets.token_hex(6))
    if args.dry_run:
        adapter = DryRunAdapter()
    else:
        from benchmark.model_adapter import HermesCodexAdapter
        adapter = HermesCodexAdapter()
    summary = run(output, adapter, dry_run=args.dry_run)
    print(json.dumps({"output_dir": str(output), "status": summary["status"], "calls": summary["model_calls"], "error": summary["error"]}))
    return 0 if summary["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
