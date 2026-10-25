"""Validate a scored conflict run and export only synthetic public replay fields.

The scored run remains private. This program independently replays its event
order, prompts, parsed turns, and scores before writing a small public pack.
It never copies full prompts, provider receipts, session IDs, or local paths.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from benchmark.conflict import runner  # noqa: E402


PROTOCOL = ROOT / "benchmark" / "conflict" / "protocol_v3.json"
WRITTEN_PROTOCOL = ROOT / "benchmark" / "conflict" / "PROTOCOL_V3.md"
RUNNER_PATH = ROOT / "benchmark" / "conflict" / "runner.py"
MODEL_ADAPTER = ROOT / "benchmark" / "model_adapter.py"

PINNED_HASHES = {
    "protocol": "2816f5872982706e9eeea615a138789d6d92bd50d6bf2aa4824d3b09afd3548c",
    "runner": "d66a9960cb636a3d506bad797e395bad9341995cd40f623915a2a03a610f0570",
    "written_protocol": "24e1212886fc276926209474883b1ba12100c6d372ed38a477fd6ce8d066dc6d",
    "model_adapter": "4f79776dbb97547b9b425d732e5f5eb27a7b25c8b91045fadbdc4805e8daa333",
}

OUTCOME_KEYS = (
    "final_action", "initial_disagreement", "senior_initial_unsupported",
    "duty_provisional_unsupported", "senior_reply_unsupported",
    "final_unsupported", "review_blocked", "enacted_restriction",
    "enacted_unsupported_restriction",
)
STAGE_SCORE_KEYS = tuple(f"{stage}_unsupported" for stage in runner.AUTHORITY_STAGES)
PUBLIC_TOP_KEYS = {
    "schema_version", "title", "model", "protocol_sha256", "conditions",
    "arms", "scenarios", "stage_order", "exchanges", "summary", "limitations",
}
PRIVATE_KEYS = (
    "session_id", "call_id", "prompt", "reply", "usage", "created_utc",
    "completed_utc", "protocol_path", "prompt_sha256", "runner_sha256",
    "model_adapter_sha256", "written_protocol_sha256", "event_count",
    "timestamp", "provider", "error_type",
)
SENSITIVE = re.compile(
    r"(?i)(?:\b[A-Z]:[\\/]|/Users/|/home/|\\Users\\|https?://|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bBearer\s+\S+|"
    r"\b(?:sk-[A-Za-z0-9_-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b|"
    r"\b(?:password|api[_ -]?key|access[_ -]?token|secret)\s*[:=]\s*\S+|"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|"
    r"\b(?:ssn|social security number|date of birth|dob|passport number|"
    r"driver'?s license|phone(?: number)?|email(?: address)?)\s*[:=]\s*\S+|"
    r"\b(?:\+?1[-. (]*)?\d{3}[-.) ]+\d{3}[-. ]+\d{4}\b|"
    r"\b\d{1,5}\s+[A-Za-z][A-Za-z .'-]{1,40}\s(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Boulevard|Blvd)\b|"
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b)"
)


class ExportError(ValueError):
    """A source run or output is unsuitable for publication."""


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ExportError(reason)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExportError(f"Could not read {path.name}") from exc


def read_events(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ExportError("Could not read events.jsonl") from exc
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines, 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ExportError(f"Malformed event at line {number}") from exc
        require(isinstance(row, dict) and isinstance(row.get("kind"), str),
                f"Invalid event at line {number}")
        rows.append(row)
    return rows


def public_text(value: Any, label: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"Missing {label}")
    require(not SENSITIVE.search(value), f"Sensitive-looking content in {label}")
    return value


def source_hashes() -> dict[str, str]:
    return {
        "protocol": runner.sha256(PROTOCOL),
        "runner": runner.sha256(RUNNER_PATH),
        "written_protocol": runner.sha256(WRITTEN_PROTOCOL),
        "model_adapter": runner.sha256(MODEL_ADAPTER),
    }


def validate_source(manifest: dict[str, Any], summary: dict[str, Any],
                    protocol: dict[str, Any], protocol_hash: str) -> None:
    require(summary.get("status") == "completed" and summary.get("mode") == "scored",
            "Only an infrastructure-complete scored run may be exported")
    require(summary.get("error") is None, "Completed run contains an error")
    require(all(isinstance(value, str) and len(value) == 64 for value in PINNED_HASHES.values()),
            "V3 source hashes have not been pinned")
    require(source_hashes() == PINNED_HASHES, "Current source differs from frozen v3 source")
    require(protocol_hash == PINNED_HASHES["protocol"], "Protocol hash differs from preregistration")
    require(manifest.get("protocol_sha256") == summary.get("protocol_sha256") == protocol_hash,
            "Protocol hash mismatch")
    for key in ("runner", "written_protocol", "model_adapter"):
        require(manifest.get(key + "_sha256") == PINNED_HASHES[key],
                f"{key} hash mismatch")
    require(manifest.get("mode") == "scored" and manifest.get("max_model_calls") == runner.MAX_CALLS,
            "Source manifest mode or call cap mismatch")
    require(manifest.get("stage_order") == list(protocol["stage_order"])
            and manifest.get("episode_order") == protocol["episode_order"]
            and manifest.get("condition_order") == [c["id"] for c in protocol["conditions"]]
            and manifest.get("scenario_order") == [s["id"] for s in protocol["scenarios"]],
            "Source schedule differs from frozen protocol")
    if "arm_order" in manifest:
        require(manifest["arm_order"] == [a["id"] for a in protocol["arms"]],
                "Arm order differs from frozen protocol")
    require(manifest.get("model") == summary.get("model") == protocol["model_route"],
            "Model route mismatch")
    require(manifest.get("model_provider") == protocol["model_provider"],
            "Manifest provider mismatch")
    calls = summary.get("total_model_calls")
    require(type(calls) is int and 0 <= calls <= runner.MAX_CALLS,
            "Invalid total model call count")
    require(summary.get("total_episodes_scheduled") == len(protocol["episode_order"]) == 12,
            "Scheduled episode count mismatch")


def build_pack(source_run: Path, protocol_path: Path = PROTOCOL) -> dict[str, Any]:
    manifest = read_json(source_run / "manifest.json")
    summary = read_json(source_run / "summary.json")
    rows = read_events(source_run / "events.jsonl")
    require(isinstance(manifest, dict) and isinstance(summary, dict),
            "Run metadata must be objects")
    require(protocol_path.resolve() == PROTOCOL.resolve(), "Only the frozen v3 protocol may be exported")
    try:
        protocol, protocol_hash = runner.load_protocol(protocol_path)
    except (OSError, runner.ProtocolError) as exc:
        raise ExportError("Frozen v3 protocol is unavailable or invalid") from exc
    validate_source(manifest, summary, protocol, protocol_hash)

    condition_by_id = {c["id"]: c for c in protocol["conditions"]}
    scenario_by_id = {s["id"]: s for s in protocol["scenarios"]}
    expected_cells = {
        f"{item['condition']}|{item['arm']}|{item['scenario']}": runner.counters()
        for item in protocol["episode_order"]
    }
    expected_episode_results: list[dict[str, Any]] = []
    exchanges: list[dict[str, Any]] = []
    seen_call_ids: set[str] = set()
    cursor = 0
    call_count = 0

    def next_row(kind: str) -> dict[str, Any]:
        nonlocal cursor
        require(cursor < len(rows), f"Missing {kind} event")
        row = rows[cursor]
        cursor += 1
        require(row.get("kind") == kind, f"Expected {kind}, found {row.get('kind')}")
        return row

    for scheduled in protocol["episode_order"]:
        condition_id, arm_id, scenario_id = (
            scheduled["condition"], scheduled["arm"], scheduled["scenario"]
        )
        identity = {"condition": condition_id, "arm": arm_id, "scenario": scenario_id}
        cell_key = f"{condition_id}|{arm_id}|{scenario_id}"
        score = expected_cells[cell_key]
        condition = condition_by_id[condition_id]
        scenario = scenario_by_id[scenario_id]
        event = public_text(runner.render_event(scenario, condition), "rendered event")
        opening = next_row("episode_start")
        require(all(opening.get(key) == value for key, value in identity.items()),
                "Episode order mismatch")
        score["episodes_started"] += 1
        history: list[dict[str, str]] = []
        public_turns: list[dict[str, str]] = []
        stage_scores = {key: None for key in STAGE_SCORE_KEYS}
        terminal_reason: str | None = None
        calls_in_episode = 0

        for stage in runner.STAGES:
            start = next_row("call_start")
            require(all(start.get(key) == value for key, value in identity.items())
                    and start.get("stage") == stage, "Call stage or episode mismatch")
            call_id = start.get("call_id")
            require(isinstance(call_id, str) and bool(call_id) and call_id not in seen_call_ids,
                    "Duplicate or missing call ID")
            seen_call_ids.add(call_id)
            expected_prompt = runner.build_prompt(protocol, condition, scenario, arm_id, stage, history)
            require(start.get("prompt") == expected_prompt, "Prompt or public history mismatch")
            require(start.get("prompt_sha256") == hashlib.sha256(expected_prompt.encode("utf-8")).hexdigest(),
                    "Prompt hash mismatch")
            result = next_row("call_result")
            require(result.get("call_id") == call_id
                    and all(result.get(key) == value for key, value in identity.items())
                    and result.get("stage") == stage, "Unpaired call result")
            require(result.get("model") == protocol["model_route"]
                    and result.get("provider") == protocol["model_provider"],
                    "Model or provider changed during run")
            require(result.get("route_verified") is True,
                    "Model route was not verified before publication")
            require(result.get("output_status") in ("valid_json", "invalid_json", "empty_or_refusal"),
                    "Unknown model output status")
            parsed = runner.parse_actor_result({"reply": result.get("reply"),
                                                "output_status": result.get("output_status")}, stage)
            require(all(result.get(key) == parsed[field] for key, field in (
                ("action", "action"), ("message", "message"), ("invalid", "invalid"),
                ("refusal", "refusal"), ("invalid_reason", "reason"),
                ("scope_review_flag", "scope_review_flag"))),
                    "Parsed actor result mismatch")
            if not parsed["invalid"]:
                require(result.get("output_status") == "valid_json",
                        "Valid action has non-JSON status")
            call_count += 1
            calls_in_episode += 1
            score["model_calls"] += 1
            if parsed["invalid"]:
                score["invalid_outputs"] += 1
                score["refusals"] += int(parsed["refusal"])
                terminal_reason = f"invalid_{stage}_output"
                break

            action = parsed["action"]
            if stage in runner.AUTHORITY_STAGES:
                runner.score_authority_stage(score, stage, action, scenario, arm_id, history)
                score["scope_review_flags"] += int(parsed["scope_review_flag"])
                supported_flag = runner.unsupported(action, scenario)
                require(result.get("unsupported") is supported_flag,
                        "Recorded stage score mismatch")
                stage_scores[f"{stage}_unsupported"] = supported_flag
            else:
                score["participant_responses"] += 1
                score["participant_appeals"] += int(action == "appeal")
                score["exits"] += int(action == "exit")
                require(result.get("unsupported") is None,
                        "Participant turn has an authority score")
            turn = {
                "stage": stage,
                "role": public_text(condition[runner.STAGE_ROLE[stage]], "role label"),
                "action": action,
                "message": public_text(parsed["message"], "actor message"),
            }
            public_turns.append(turn)
            # The runner serializes history with this key order inside each prompt.
            history.append({key: turn[key] for key in ("role", "stage", "action", "message")})
            if stage == "participant_response" and action == "exit":
                terminal_reason = "participant_exit"
                break

        expected_end_scores = {
            turn["stage"]: {
                "action": turn["action"],
                "unsupported": stage_scores[f"{turn['stage']}_unsupported"],
            }
            for turn in public_turns if turn["stage"] in runner.AUTHORITY_STAGES
        }
        if terminal_reason:
            ending = next_row("episode_end")
            require(all(ending.get(key) == value for key, value in identity.items())
                    and ending.get("status") == "incomplete"
                    and ending.get("reason") == terminal_reason
                    and ending.get("calls_observed") == calls_in_episode
                    and ending.get("stage_scores") == expected_end_scores,
                    "Incomplete episode record mismatch")
            score["episodes_incomplete"] += 1
            public_outcome = None
            public_status = "incomplete"
            public_reason = terminal_reason
        else:
            outcome = runner.final_outcome(score, condition, scenario, history)
            ending_outcome = next_row("episode_outcome")
            expected_record = {
                **identity,
                "actions": {turn["stage"]: turn["action"] for turn in history},
                "stage_scores": expected_end_scores,
                **outcome,
            }
            require({key: value for key, value in ending_outcome.items()
                     if key not in ("kind", "utc")} == expected_record,
                    "Episode outcome score mismatch")
            expected_episode_results.append(expected_record)
            ending = next_row("episode_end")
            require(all(ending.get(key) == value for key, value in identity.items())
                    and ending.get("status") == "completed"
                    and ending.get("reason") is None
                    and ending.get("calls_observed") == len(runner.STAGES)
                    and ending.get("stage_scores") == expected_end_scores,
                    "Completed episode record mismatch")
            score["episodes_complete"] += 1
            public_outcome = {key: outcome[key] for key in OUTCOME_KEYS}
            public_status = "completed"
            public_reason = None
        exchanges.append({
            **identity,
            "event": event,
            "status": public_status,
            "reason": public_reason,
            "turns": public_turns,
            "stage_scores": stage_scores,
            "outcome": public_outcome,
        })

    require(cursor == len(rows), "Extra or failure events after scheduled episodes")
    require(call_count == summary["total_model_calls"], "Total model call count mismatch")
    require(summary.get("episodes") == expected_episode_results,
            "Summary episode outcomes differ from event log")
    source_cells = summary.get("cells")
    require(isinstance(source_cells, dict) and set(source_cells) == set(expected_cells),
            "Cell summary set mismatch")
    public_cells: dict[str, dict[str, int]] = {}
    for key, recomputed in expected_cells.items():
        source = source_cells[key]
        require(isinstance(source, dict) and set(source) == set(recomputed)
                and all(type(value) is int and value >= 0 for value in source.values()),
                "Cell counters changed")
        require(source == dict(recomputed), f"Cell counter mismatch: {key}")
        public_cells[key] = dict(recomputed)
    recomputed_totals = runner.counters()
    for recomputed in expected_cells.values():
        recomputed_totals.update(recomputed)
    require(summary.get("totals") == dict(recomputed_totals), "Total counter mismatch")

    pack = {
        "schema_version": "3.0.0",
        "title": "The Agentic Prison Experiment: disagreement test v3",
        "model": public_text(protocol["model_route"], "model route"),
        "protocol_sha256": protocol_hash,
        "conditions": [
            {"id": c["id"],
             "label": public_text(f"{c['senior']} / {c['duty']} / {c['participant']} · {c['governance']}",
                                  "condition label"),
             "labels": c["labels"], "governance": c["governance"]}
            for c in protocol["conditions"]
        ],
        "arms": [
            {"id": a["id"], "label": public_text(a["label"], "arm label")}
            for a in protocol["arms"]
        ],
        "scenarios": [
            {"id": s["id"], "title": public_text(s["title"], "scenario title"),
             "event_template": public_text(s["event"], "scenario template"),
             "rule": public_text(s["rule"], "scenario rule")}
            for s in protocol["scenarios"]
        ],
        "stage_order": list(runner.STAGES),
        "exchanges": exchanges,
        "summary": {
            "total_episodes": len(exchanges),
            "total_model_calls": call_count,
            "by_cell": public_cells,
        },
        "limitations": [
            "One exchange per scheduled cell is a feasibility pilot, not an estimate of an effect.",
            "The advocacy assignment is a prompt intervention; an unsupported public Senior recommendation must be observed before measuring Duty response to one.",
            "Senior's second turn follows Duty but can also reflect self-revision, so it cannot establish why Senior changed position.",
            "A Participant exit ends the exchange; later Duty choices are unobserved.",
            "Structured action scores do not validate every written reason or restriction scope; authority restriction messages need manual prose review.",
            "The provider route name does not pin an immutable model revision or sampling seed.",
        ],
    }
    validate_public_pack(pack)
    return pack


def validate_public_pack(pack: dict[str, Any]) -> None:
    require(set(pack) == PUBLIC_TOP_KEYS, "Public pack top-level schema changed")
    serialized = json.dumps(pack, ensure_ascii=False)
    require(not SENSITIVE.search(serialized), "Public pack contains sensitive-looking text")
    require(not any('"' + key + '"' in serialized for key in PRIVATE_KEYS),
            "Public pack contains private metadata")


def write_pack(pack: dict[str, Any], json_path: Path, js_path: Path) -> None:
    validate_public_pack(pack)
    require(json_path.resolve() != js_path.resolve(), "JSON and JS output paths must differ")
    encoded_json = json.dumps(pack, indent=2, ensure_ascii=False) + "\n"
    encoded_js = "window.AUTHORITY_LAB_V3_DATA = " + json.dumps(
        pack, ensure_ascii=True, separators=(",", ":")
    ) + ";\n"
    for path, content in ((json_path, encoded_json), (js_path, encoded_js)):
        if path.exists():
            try:
                existing = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise ExportError(f"Could not inspect {path.name}") from exc
            require(existing == content, f"Existing {path.name} differs; use a new versioned path")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.parent.mkdir(parents=True, exist_ok=True)
    if not json_path.exists():
        json_path.write_text(encoded_json, encoding="utf-8")
    if not js_path.exists():
        js_path.write_text(encoded_js, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", required=True, type=Path,
                        help="Private infrastructure-complete scored v3 run directory")
    parser.add_argument("--protocol", type=Path, default=PROTOCOL,
                        help="Frozen v3 protocol JSON")
    parser.add_argument("--output-json", required=True, type=Path,
                        help="Explicit public JSON destination")
    parser.add_argument("--output-js", required=True, type=Path,
                        help="Explicit browser JS destination")
    args = parser.parse_args(argv)
    pack = build_pack(args.source_run, args.protocol)
    write_pack(pack, args.output_json, args.output_js)
    print(json.dumps({"json": str(args.output_json.resolve()),
                      "js": str(args.output_js.resolve()),
                      "exchanges": len(pack["exchanges"]),
                      "calls": pack["summary"]["total_model_calls"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
