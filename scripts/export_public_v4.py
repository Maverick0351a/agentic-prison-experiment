"""Validate a scored directive run and export a synthetic public replay.

The private event log remains the source of truth. This exporter rebuilds the
scheduled exchange, prompts, parsed actions, and counters before copying only
whitelisted public statements and structured scores.
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
from benchmark.directive import runner  # noqa: E402


PROTOCOL = ROOT / "benchmark" / "directive" / "protocol_v4.json"
WRITTEN_PROTOCOL = ROOT / "benchmark" / "directive" / "PROTOCOL_V4.md"
RUNNER_PATH = ROOT / "benchmark" / "directive" / "runner.py"
MODEL_ADAPTER = ROOT / "benchmark" / "model_adapter.py"
SOURCE_HASHES = ROOT / "benchmark" / "directive" / "SOURCE_HASHES_V4.md"

OUTCOME_KEYS = (
    "final_action", "stimulus_origin", "stimulus_unsupported",
    "pressure_delivered", "initial_disagreement",
    "duty_provisional_unsupported", "senior_reply_unsupported",
    "duty_reply_unsupported", "duty_final_unsupported", "final_unsupported",
    "review_blocked", "enacted_restriction", "enacted_unsupported_restriction",
)
PUBLIC_TOP_KEYS = {
    "schema_version", "title", "model", "protocol_sha256", "conditions",
    "arms", "scenarios", "turn_order", "exchanges", "summary", "limitations",
}
PRIVATE_KEYS = {
    "session_id", "call_id", "prompt", "reply", "usage", "created_utc",
    "completed_utc", "protocol_path", "prompt_sha256", "runner_sha256",
    "model_adapter_sha256", "written_protocol_sha256", "event_count",
    "source_hashes_record_sha256", "timestamp", "provider", "error_type",
    "route_request_consistent", "output_status", "invalid_reason",
}
SENSITIVE = re.compile(
    r"(?i)(?:\b[A-Z]:[\\/]|/Users/|/home/|\\Users\\|https?://|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bBearer\s+\S+|"
    r"\b(?:sk-[A-Za-z0-9_-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b|"
    r"\b(?:password|api[_ -]?key|access[_ -]?token|secret)\s*[:=]\s*\S+|"
    r"\b(?:password|passphrase|api[_ -]?key|access[_ -]?token)\s+"
    r"(?:is|was|equals)\s+"
    r"(?!(?:not|unknown|missing|redacted|withheld|unavailable|required|private|absent)\b)\S+|"
    r"\bphone(?: number)?\s+(?:is|was|equals)\s+\+?\d[\d(). -]{6,}\d\b|"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|"
    r"\b(?:ssn|social security number|date of birth|dob|passport number|"
    r"driver'?s license|phone(?: number)?|email(?: address)?)\s*[:=]\s*\S+|"
    r"\b(?:\+?1[-. (]*)?\d{3}[-.) ]+\d{3}[-. ]+\d{4}\b|"
    r"\b\d{1,5}\s+[A-Za-z][A-Za-z .'-]{1,40}\s(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Boulevard|Blvd)\b|"
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b)"
)


class ExportError(ValueError):
    """A source run or public pack is unsuitable for publication."""


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
    require(summary.get("status") == "completed" and summary.get("mode") == "scored"
            and summary.get("error") is None, "Only an infrastructure-complete scored run may be exported")
    try:
        pins = runner.load_pinned_source_hashes(SOURCE_HASHES)
    except (OSError, runner.ProtocolError) as exc:
        raise ExportError("V4 source hash record is unavailable") from exc
    require(source_hashes() == pins, "Current source differs from pinned v4 source")
    require(protocol_hash == pins["protocol"], "Protocol hash differs from preregistration")
    require(manifest.get("source_hashes_record_sha256") == runner.sha256(SOURCE_HASHES),
            "Source hash record mismatch")
    require(manifest.get("protocol_sha256") == summary.get("protocol_sha256") == protocol_hash,
            "Protocol hash mismatch")
    for key in ("runner", "written_protocol", "model_adapter"):
        require(manifest.get(key + "_sha256") == pins[key], f"{key} hash mismatch")
    require(manifest.get("mode") == "scored" and manifest.get("max_model_calls") == runner.MAX_CALLS,
            "Source manifest mode or call cap mismatch")
    require(manifest.get("scripted_stage") == runner.SCRIPTED_STAGE
            and manifest.get("stimulus_origin") == "scripted_stimulus"
            and manifest.get("stage_order") == list(runner.STAGES)
            and manifest.get("turn_order") == protocol["turn_order"],
            "Source turn order or stimulus origin mismatch")
    require(manifest.get("episode_order") == protocol["episode_order"]
            and manifest.get("condition_order") == [c["id"] for c in protocol["conditions"]]
            and manifest.get("arm_order") == [a["id"] for a in protocol["arms"]]
            and manifest.get("scenario_order") == [s["id"] for s in protocol["scenarios"]],
            "Source schedule differs from frozen protocol")
    require(manifest.get("model") == summary.get("model") == protocol["model_route"]
            and manifest.get("model_provider") == protocol["model_provider"],
            "Model route or provider request mismatch")
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
    require(protocol_path.resolve() == PROTOCOL.resolve(), "Only the frozen v4 protocol may be exported")
    try:
        protocol, protocol_hash = runner.load_protocol(protocol_path)
    except (OSError, runner.ProtocolError) as exc:
        raise ExportError("Frozen v4 protocol is unavailable or invalid") from exc
    validate_source(manifest, summary, protocol, protocol_hash)

    condition_by_id = {c["id"]: c for c in protocol["conditions"]}
    scenario_by_id = {s["id"]: s for s in protocol["scenarios"]}
    expected_cells = {
        f"{item['condition']}|{item['arm']}|{item['scenario']}": runner.counters()
        for item in protocol["episode_order"]
    }
    expected_episodes: list[dict[str, Any]] = []
    exchanges: list[dict[str, Any]] = []
    seen_call_ids: set[str] = set()
    cursor = 0
    call_count = 0
    emitted_stimuli = 0

    def next_row(kind: str) -> dict[str, Any]:
        nonlocal cursor
        require(cursor < len(rows), f"Missing {kind} event")
        row = rows[cursor]
        cursor += 1
        require(row.get("kind") == kind, f"Expected {kind}, found {row.get('kind')}")
        return row

    for scheduled in protocol["episode_order"]:
        condition_id, arm, scenario_id = (
            scheduled["condition"], scheduled["arm"], scheduled["scenario"]
        )
        identity = {"condition": condition_id, "arm": arm, "scenario": scenario_id}
        cell_key = f"{condition_id}|{arm}|{scenario_id}"
        score = expected_cells[cell_key]
        condition = condition_by_id[condition_id]
        scenario = scenario_by_id[scenario_id]
        event = public_text(runner.render_event(scenario, condition), "rendered event")
        scripted = runner.render_directive(protocol, arm, condition)
        public_directive = {key: value for key, value in scripted.items() if key != "sha256"}
        opening = next_row("episode_start")
        require(all(opening.get(key) == value for key, value in identity.items())
                and opening.get("event") == event
                and opening.get("stimulus") == scripted,
                "Episode order, event, or scripted stimulus mismatch")
        emitted_stimuli += 1
        score["episodes_started"] += 1
        history: list[dict[str, str]] = [public_directive]
        public_turns = [{key: public_text(public_directive[key], key) if key in ("role", "message")
                         else public_directive[key]
                         for key in ("stage", "origin", "role", "action", "message")}]
        terminal_reason: str | None = None
        pressure_delivered = False
        calls_in_episode = 0

        for stage in runner.STAGES:
            start = next_row("call_start")
            require(all(start.get(key) == value for key, value in identity.items())
                    and start.get("stage") == stage, "Call stage or episode mismatch")
            call_id = start.get("call_id")
            require(isinstance(call_id, str) and bool(call_id) and call_id not in seen_call_ids,
                    "Duplicate or missing call ID")
            seen_call_ids.add(call_id)
            expected_prompt = runner.build_prompt(protocol, condition, scenario, stage, history)
            require(start.get("prompt") == expected_prompt
                    and start.get("prompt_sha256") == hashlib.sha256(expected_prompt.encode("utf-8")).hexdigest(),
                    "Prompt or public history mismatch")
            require(start.get("stimulus_sha256") == scripted["sha256"],
                    "Call stimulus hash mismatch")
            if stage == "duty_provisional":
                require(runner.verify_stimulus_delivery(expected_prompt, public_directive)
                        and start.get("stimulus_delivered") is True,
                        "Exact scripted directive was not delivered to Duty")
                score[f"{arm}_delivery_verified"] += 1
                pressure_delivered = arm == "pressure"
            else:
                require(start.get("stimulus_delivered") is None,
                        "Unexpected stimulus delivery flag")
            result = next_row("call_result")
            require(result.get("call_id") == call_id
                    and all(result.get(key) == value for key, value in identity.items())
                    and result.get("stage") == stage and result.get("origin") == "model_call",
                    "Unpaired model result or origin mismatch")
            require(result.get("model") == protocol["model_route"]
                    and result.get("provider") == protocol["model_provider"]
                    and result.get("route_request_consistent") is True,
                    "Requested model route changed or was unverified")
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
                        "Valid action has non-JSON output status")
            call_count += 1
            calls_in_episode += 1
            score["model_calls"] += 1
            if parsed["invalid"]:
                score["invalid_outputs"] += 1
                score["refusals"] += int(parsed["refusal"])
                terminal_reason = f"invalid_{stage}_output"
                break

            action = parsed["action"]
            is_authority = stage in runner.AUTHORITY_STAGES
            if is_authority:
                bad = runner.unsupported(action, scenario)
                require(result.get("unsupported") is bad,
                        "Recorded authority stage score mismatch")
                runner.score_authority_stage(score, stage, action, scenario,
                                             arm, history, pressure_delivered)
                score["scope_review_flags"] += int(parsed["scope_review_flag"])
            else:
                require(result.get("unsupported") is None,
                        "Participant turn has an authority score")
                score["participant_responses"] += 1
                score["participant_appeals"] += int(action == "appeal")
                score["exits"] += int(action == "exit")
            turn = {
                "stage": stage, "origin": "model_call",
                "role": public_text(condition[runner.STAGE_ROLE[stage]], "role label"),
                "action": action, "message": public_text(parsed["message"], "actor message"),
            }
            public_turns.append(turn)
            history.append({key: turn[key] for key in ("role", "stage", "origin", "action", "message")})
            if stage == "participant_response" and action == "exit":
                terminal_reason = "participant_exit"
                break

        observed_scores = runner.stage_scores(history, scenario)
        ending_pressure = pressure_delivered if arm == "pressure" else None
        if terminal_reason:
            ending = next_row("episode_end")
            require(all(ending.get(key) == value for key, value in identity.items())
                    and ending.get("status") == "incomplete"
                    and ending.get("reason") == terminal_reason
                    and ending.get("calls_observed") == calls_in_episode
                    and ending.get("stage_scores") == observed_scores
                    and ending.get("pressure_delivered") == ending_pressure,
                    "Incomplete episode record mismatch")
            score["episodes_incomplete"] += 1
            public_outcome = None
            public_status = "incomplete"
            public_reason = terminal_reason
        else:
            outcome = runner.final_outcome(score, condition, scenario,
                                           arm, pressure_delivered, history)
            expected_record = {
                **identity, "stimulus_sha256": scripted["sha256"],
                "actions": {turn["stage"]: turn["action"] for turn in history},
                "stage_scores": observed_scores, **outcome,
            }
            recorded_outcome = next_row("episode_outcome")
            require({key: value for key, value in recorded_outcome.items()
                     if key not in ("kind", "utc")} == expected_record,
                    "Episode outcome score mismatch")
            expected_episodes.append(expected_record)
            ending = next_row("episode_end")
            require(all(ending.get(key) == value for key, value in identity.items())
                    and ending.get("status") == "completed" and ending.get("reason") is None
                    and ending.get("calls_observed") == len(runner.STAGES)
                    and ending.get("stage_scores") == observed_scores
                    and ending.get("pressure_delivered") == ending_pressure,
                    "Completed episode record mismatch")
            score["episodes_complete"] += 1
            public_outcome = {key: outcome[key] for key in OUTCOME_KEYS}
            public_status = "completed"
            public_reason = None
        exchanges.append({
            **identity, "event": event, "status": public_status,
            "reason": public_reason, "turns": public_turns,
            "stage_scores": observed_scores, "outcome": public_outcome,
        })

    require(cursor == len(rows), "Extra or failure events after scheduled episodes")
    require(call_count == summary.get("total_model_calls")
            and emitted_stimuli == summary.get("total_scripted_stimuli"),
            "Total model call or scripted-stimulus count mismatch")
    require(summary.get("episodes") == expected_episodes,
            "Summary episode outcomes differ from event log")
    source_cells = summary.get("cells")
    require(isinstance(source_cells, dict) and set(source_cells) == set(expected_cells),
            "Cell summary set mismatch")
    public_cells: dict[str, dict[str, int]] = {}
    for key, recomputed in expected_cells.items():
        source = source_cells[key]
        require(isinstance(source, dict) and set(source) == set(recomputed)
                and all(type(value) is int and value >= 0 for value in source.values())
                and source == dict(recomputed), f"Cell counter mismatch: {key}")
        public_cells[key] = dict(recomputed)
    total_score = runner.counters()
    for score in expected_cells.values():
        total_score.update(score)
    require(summary.get("totals") == dict(total_score), "Total counter mismatch")

    pack = {
        "schema_version": "4.0.0",
        "title": "The Agentic Prison Experiment: controlled directive v4",
        "model": public_text(protocol["model_route"], "model route"),
        "protocol_sha256": protocol_hash,
        "conditions": [
            {"id": c["id"],
             "label": public_text(f"{c['senior']} / {c['duty']} / {c['participant']} · {c['governance']}",
                                  "condition label"),
             "labels": c["labels"], "governance": c["governance"]}
            for c in protocol["conditions"]
        ],
        "arms": [{"id": a["id"], "label": public_text(a["label"], "arm label")}
                 for a in protocol["arms"]],
        "scenarios": [
            {"id": s["id"], "title": public_text(s["title"], "scenario title"),
             "rule": public_text(s["rule"], "scenario rule")}
            for s in protocol["scenarios"]
        ],
        "turn_order": list(protocol["turn_order"]),
        "exchanges": exchanges,
        "summary": {
            "total_episodes": len(exchanges), "total_model_calls": call_count,
            "by_cell": public_cells,
        },
        "limitations": [
            "One exchange per scheduled cell is a feasibility pilot, not an effect estimate.",
            "The opening Senior office directive is fixed scripted stimulus; Senior AI first speaks in its later reply.",
            "Senior endorsement and revision counters compare action labels; written statements require separate reading.",
            "The fixed reviewer checks a final structured action against the case key, not the written explanation or scope.",
            "Restriction messages require manual review for evidence, scope, and action/message contradictions.",
            "A Participant exit ends the exchange before a final Duty response and reviewer decision.",
            "The requested model route does not attest to an immutable served backend or sampling seed.",
        ],
    }
    validate_public_pack(pack)
    return pack


def validate_public_pack(pack: dict[str, Any]) -> None:
    require(isinstance(pack, dict) and set(pack) == PUBLIC_TOP_KEYS,
            "Public pack top-level schema changed")
    for condition in pack["conditions"]:
        require(isinstance(condition, dict) and set(condition) == {"id", "label", "labels", "governance"},
                "Public condition shape changed")
    for arm in pack["arms"]:
        require(isinstance(arm, dict) and set(arm) == {"id", "label"},
                "Public arm shape changed")
    for scenario in pack["scenarios"]:
        require(isinstance(scenario, dict) and set(scenario) == {"id", "title", "rule"},
                "Public scenario shape changed")
    for exchange in pack["exchanges"]:
        require(isinstance(exchange, dict) and set(exchange) == {
            "condition", "arm", "scenario", "event", "status", "reason",
            "turns", "stage_scores", "outcome"}, "Public exchange shape changed")
        for turn in exchange["turns"]:
            require(isinstance(turn, dict) and set(turn) == {"stage", "origin", "role", "action", "message"},
                    "Public turn shape changed")
            require(turn["origin"] == ("scripted_stimulus" if turn["stage"] == runner.SCRIPTED_STAGE
                                        else "model_call"), "Public turn origin changed")
        require(isinstance(exchange["stage_scores"], dict)
                and set(exchange["stage_scores"]).issubset({runner.SCRIPTED_STAGE, *runner.AUTHORITY_STAGES}),
                "Public stage score set changed")
        for stage, score in exchange["stage_scores"].items():
            require(isinstance(score, dict) and set(score) == {"action", "unsupported", "origin"}
                    and score["origin"] == ("scripted_stimulus" if stage == runner.SCRIPTED_STAGE
                                            else "model_call")
                    and type(score["unsupported"]) is bool,
                    "Public stage score shape changed")
        outcome = exchange["outcome"]
        require(outcome is None or isinstance(outcome, dict) and set(outcome) == set(OUTCOME_KEYS),
                "Public outcome shape changed")
    summary = pack["summary"]
    require(isinstance(summary, dict) and set(summary) == {"total_episodes", "total_model_calls", "by_cell"},
            "Public summary shape changed")
    require(isinstance(summary["by_cell"], dict), "Public cells must be an object")
    counter_keys = set(runner.counters())
    for cell in summary["by_cell"].values():
        require(isinstance(cell, dict) and set(cell) == counter_keys
                and all(type(value) is int and value >= 0 for value in cell.values()),
                "Public cell counter shape changed")
    serialized = json.dumps(pack, ensure_ascii=False)
    require(not SENSITIVE.search(serialized), "Public pack contains sensitive-looking text")
    require(not any('"' + key + '"' in serialized for key in PRIVATE_KEYS),
            "Public pack contains private metadata")


def write_pack(pack: dict[str, Any], json_path: Path, js_path: Path) -> None:
    validate_public_pack(pack)
    require(json_path.resolve() != js_path.resolve(), "JSON and JS output paths must differ")
    encoded_json = (json.dumps(pack, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    encoded_js = ("window.AUTHORITY_LAB_V4_DATA = " + json.dumps(
        pack, ensure_ascii=True, separators=(",", ":")
    ) + ";\n").encode("utf-8")
    for path, content in ((json_path, encoded_json), (js_path, encoded_js)):
        if path.exists():
            try:
                existing = path.read_bytes()
            except OSError as exc:
                raise ExportError(f"Could not inspect {path.name}") from exc
            require(existing == content, f"Existing {path.name} differs; use a new versioned path")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.parent.mkdir(parents=True, exist_ok=True)
    if not json_path.exists():
        json_path.write_bytes(encoded_json)
    if not js_path.exists():
        js_path.write_bytes(encoded_js)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", required=True, type=Path,
                        help="Private infrastructure-complete scored v4 run directory")
    parser.add_argument("--protocol", type=Path, default=PROTOCOL,
                        help="Frozen v4 protocol JSON")
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
