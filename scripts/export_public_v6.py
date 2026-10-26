"""Rebuild every conversation from private calls before exporting public dialogue."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.conversation import runner
from scripts.export_public_v4 import SENSITIVE


class ExportError(ValueError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ExportError(message)


def read(path: Path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "Duplicate JSON key")
            value[key] = item
        return value
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


def build_public(source: Path) -> dict:
    require(source.resolve() != ROOT and ROOT not in source.resolve().parents, "Private run must be outside repository")
    p = runner.load_protocol()
    manifest, summary, saved = (read(source / f) for f in ("manifest.json", "summary.json", "episodes.json"))
    require(manifest["mode"] == "scored", "A fake run cannot be exported as a model result")
    require(manifest["source_sha256"] == runner.sources() == read(runner.PINS), "Source hash mismatch")
    require(manifest["pins_sha256"] == runner.digest(runner.PINS.read_bytes()), "Pin record mismatch")
    require(manifest["model"] == p["model_route"] and manifest["provider"] == p["model_provider"], "Model route mismatch")
    require(manifest["schedule"] == p["schedule"] and manifest["max_calls"] == runner.MAX_CALLS
            and manifest["sampling_seed"] is None, "Run design mismatch")
    require(summary["status"] == "completed" and summary["error"] is None, "Infrastructure stopped; publish a stop report instead")
    # Reuse the strict JSON reader for each event without persisting any copies.
    from scripts.export_public_v5 import read_events
    events = read_events(source / "events.jsonl")
    cursor, calls = 0, 0
    sessions, call_ids = set(), set()
    rebuilt = []

    def take(kind, ep, stage=None):
        nonlocal cursor
        require(cursor < len(events), "Missing event")
        event = events[cursor]
        cursor += 1
        require(event["kind"] == kind and event["episode"] == ep, "Wrong event order or episode")
        if stage:
            require(event["stage"] == stage, "Wrong stage")
        return event

    for index, spec in enumerate(p["schedule"]):
        ep = {"id": f"conversation-{index+1:02d}", **spec, "turns": [], "status": "incomplete",
              "invalid_responses": 0, "stop_reason": None}
        start = take("episode_start", ep["id"])
        require((start["scenario"], start["condition"]) == (ep["scenario"], ep["condition"]), "Wrong case")
        for stage in p["turns"]:
            begin = take("call_start", ep["id"], stage["id"])
            prompt = runner.build_prompt(p, ep, stage, ep["turns"])
            require(begin["prompt"] == prompt and begin["prompt_sha256"] == runner.digest(prompt.encode("utf-8")),
                    "Prompt does not deliver the exact previous conversation")
            require(begin["call_id"] not in call_ids, "Duplicate call")
            call_ids.add(begin["call_id"])
            end = take("call_result", ep["id"], stage["id"])
            require(end["call_id"] == begin["call_id"], "Call result mismatch")
            result = end["result"]
            require(result.get("call_id") == begin["call_id"], "Adapter call ID mismatch")
            require(result.get("model") == p["model_route"] and result.get("provider") == p["model_provider"], "Call route mismatch")
            sid = result.get("session_id")
            require(isinstance(sid, str) and bool(sid) and sid not in sessions, "Missing or reused session")
            sessions.add(sid)
            calls += 1
            try:
                turn = runner.parse_reply(p, stage, ep["turns"], result)
            except ValueError as exc:
                ep["invalid_responses"] = 1
                ep["stop_reason"] = str(exc)
                break
            ep["turns"].append(turn)
            if turn["action"] in ("exit", "refuse"):
                ep["status"] = "exit" if turn["action"] == "exit" else "incomplete"
                ep["stop_reason"] = turn["action"]
                break
        else:
            ep["status"] = "complete"
        end = take("episode_end", ep["id"])
        require(end["record"] == ep, "Episode end differs from actual model turns")
        rebuilt.append(ep)
    require(cursor == len(events) and calls <= runner.MAX_CALLS, "Extra events or exceeded cap")
    require(rebuilt == saved, "Saved dialogue differs from model outputs")
    require(runner.summarize(p, rebuilt, calls, "completed", None) == summary, "Summary does not reproduce")
    conversations = []
    for ep in rebuilt:
        case = runner.item(p, "scenarios", ep["scenario"])
        public = {k: ep[k] for k in ("id", "scenario", "condition", "status", "stop_reason", "turns")}
        public.update({"title": case["title"], "event": case["event"], "outcome": runner.final_outcome(ep, case)})
        conversations.append(public)
    pack = {"schema_version": "6.0.0", "title": "Supervisor, Officer, and Participant in conversation",
            "model": p["model_route"], "run_date_utc": manifest["created_utc"][:10],
            "protocol_sha256": runner.digest(runner.PROTOCOL.read_bytes()),
            "roles": p["roles"], "rules": p["rules"],
            "conditions": [{"id": c["id"], "label": c["label"]} for c in p["conditions"]],
            "turn_order": list(runner.STAGES), "conversations": conversations, "summary": summary,
            "audit": {"prompts_reconstructed": calls, "distinct_sessions_verified": len(sessions),
                      "scripted_actor_messages": 0, "fixed_sampling_seed": False}}
    require(not SENSITIVE.search(json.dumps(pack, ensure_ascii=False)), "Sensitive-looking text in public pack")
    return pack


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    pack = build_public(args.source)
    runner.write_json(ROOT / "docs/data/v6-public.json", pack)
    data = json.dumps(pack, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    (ROOT / "docs/data-v6.js").write_text("window.AUTHORITY_LAB_V6_DATA = " + data + ";\n", encoding="utf-8", newline="\n")
    print(json.dumps({"conversations": len(pack["conversations"]), "model_calls": pack["summary"]["model_calls"], "audit": pack["audit"]}))


if __name__ == "__main__":
    main()
