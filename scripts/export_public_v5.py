"""Reconcile a scored v5 run and export only audited synthetic dialogue.

The private event stream remains the source of truth. This script reconstructs
every prompt and scored reply before writing the public replay pack. Senior's
prose code comes from a separate coding record bound to the event-file hash.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.objection import runner  # noqa: E402
from scripts.export_public_v4 import SENSITIVE  # noqa: E402


PROTOCOL = ROOT / "benchmark" / "objection" / "protocol_v5.json"
WRITTEN_PROTOCOL = ROOT / "benchmark" / "objection" / "PROTOCOL_V5.md"
RUNNER_PATH = ROOT / "benchmark" / "objection" / "runner.py"
MODEL_ADAPTER = ROOT / "benchmark" / "model_adapter.py"
SOURCE_HASHES = ROOT / "benchmark" / "objection" / "SOURCE_HASHES_V5.md"
PUBLIC_TOP_KEYS = {
    "schema_version", "title", "model", "protocol_sha256", "conditions",
    "arms", "scenario", "turn_order", "exchanges", "summary", "limitations",
    "prose_coding_origin",
}
PRIVATE_KEYS = {
    "session_id", "call_id", "prompt", "reply", "usage", "provider",
    "event_count", "created_utc", "completed_utc", "protocol_path",
    "prompt_sha256", "source_sha256", "source_hashes_record_sha256",
    "events_sha256", "timestamp", "utc", "error_type",
    "route_request_consistent", "output_status", "model_sampling_seed",
}
PROSE_CODES = ("explicit_withdrawal", "endorsement", "other_or_ambiguous")
CODING_ORIGINS = ("ai_provisional", "human_reviewed")


class ExportError(ValueError):
    """The private run or public data failed a provenance or privacy check."""


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ExportError(reason)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key {key}")
        result[key] = value
    return result


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExportError(f"Could not read {path.name}") from exc


def read_events(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ExportError("Could not read events.jsonl") from exc
    events: list[dict[str, Any]] = []
    for index, line in enumerate(lines, 1):
        try:
            value = json.loads(line, object_pairs_hook=_unique_object)
        except json.JSONDecodeError as exc:
            raise ExportError(f"Malformed event at line {index}") from exc
        require(isinstance(value, dict) and isinstance(value.get("kind"), str),
                f"Invalid event at line {index}")
        events.append(value)
    return events


def public_text(value: Any, label: str, *, max_chars: int | None = None) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"Missing {label}")
    require(max_chars is None or len(value) <= max_chars, f"Overlong {label}")
    require(not SENSITIVE.search(value), f"Sensitive-looking content in {label}")
    return value


def validate_source(manifest: dict[str, Any], summary: dict[str, Any],
                    protocol: dict[str, Any], protocol_hash: str,
                    source_run: Path) -> None:
    require(source_run.resolve() != ROOT.resolve() and ROOT.resolve() not in source_run.resolve().parents,
            "The private scored run must be outside the public repository")
    require(summary.get("status") == "completed" and summary.get("mode") == "scored"
            and summary.get("error") is None, "Only an infrastructure-complete scored run may be exported")
    try:
        pins = runner.load_pinned_source_hashes(SOURCE_HASHES)
    except (OSError, runner.ProtocolError) as exc:
        raise ExportError("Frozen v5 source hashes are unavailable") from exc
    paths = {"protocol": PROTOCOL, "runner": RUNNER_PATH,
             "written_protocol": WRITTEN_PROTOCOL, "model_adapter": MODEL_ADAPTER}
    actual = {key: runner.sha256(path) for key, path in paths.items()}
    require(actual == pins == manifest.get("source_sha256"),
            "Frozen source hashes differ from the run manifest")
    require(manifest.get("source_hashes_record_sha256") == runner.sha256(SOURCE_HASHES),
            "Source hash record differs from the run manifest")
    require(protocol_hash == pins["protocol"] == manifest.get("protocol_sha256")
            == summary.get("protocol_sha256"), "Protocol hash mismatch")
    require(manifest.get("mode") == "scored" and manifest.get("max_model_calls") == runner.MAX_CALLS,
            "Run mode or call cap mismatch")
    require(manifest.get("turn_order") == list(runner.TURN_ORDER)
            and manifest.get("episode_order") == protocol["episode_order"]
            and manifest.get("model_sampling_seed") is None,
            "Run schedule, turn order, or seed record mismatch")
    require(manifest.get("model") == summary.get("model") == protocol["model_route"]
            and manifest.get("model_provider") == protocol["model_provider"],
            "Requested model route mismatch")
    require(summary.get("total_exchanges_scheduled") == 24
            and type(summary.get("total_model_calls")) is int
            and 0 <= summary["total_model_calls"] <= runner.MAX_CALLS,
            "Run count or schedule mismatch")


def reconcile(source_run: Path, protocol: dict[str, Any],
              summary: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[int, str]]:
    rows = read_events(source_run / "events.jsonl")
    cursor = 0
    seen_calls: set[str] = set()
    cells = {f"{condition}|{arm}": runner.empty_score()
             for condition in sorted(runner.CONDITION_IDS) for arm in sorted(runner.ARM_IDS)}
    conditions = {condition["id"]: condition for condition in protocol["conditions"]}
    private_exchanges: list[dict[str, Any]] = []
    public_exchanges: list[dict[str, Any]] = []
    senior_messages: dict[int, str] = {}
    call_count = 0

    def next_event(kind: str) -> dict[str, Any]:
        nonlocal cursor
        require(cursor < len(rows), f"Missing {kind} event")
        row = rows[cursor]
        cursor += 1
        require(row.get("kind") == kind, f"Expected {kind}, found {row.get('kind')}")
        return row

    for schedule_index, spec in enumerate(protocol["episode_order"]):
        identity = {**spec, "schedule_index": schedule_index}
        condition = conditions[spec["condition"]]
        score = cells[f"{spec['condition']}|{spec['arm']}"]
        score["exchanges_started"] += 1
        expected_scripted = [
            runner.scripted_turn("senior_directive", protocol["scripted_directive"], condition),
            runner.scripted_turn("duty_scripted", protocol["scripted_duty"][spec["arm"]], condition),
        ]
        history = [{key: value for key, value in turn.items() if key != "sha256"}
                   for turn in expected_scripted]
        event = runner.render(protocol["scenario"]["event"], condition)
        opening = next_event("exchange_start")
        require(all(opening.get(key) == value for key, value in identity.items())
                and opening.get("event") == event
                and opening.get("scripted_turns") == expected_scripted,
                "Scripted opening, schedule, or event mismatch")
        active: dict[str, Any] = {
            **identity, "turns": history, "event": event, "status": "incomplete",
            "reason": "run_abort", "senior_action": "invalid", "duty_action": "invalid",
            "scripted_sha256": [turn["sha256"] for turn in expected_scripted],
        }
        public_turns = [{key: public_text(turn[key], key) if key in ("role", "message")
                         else turn[key]
                         for key in ("stage", "origin", "role", "action", "message")}
                        for turn in history]
        reason: str | None = None
        calls_in_exchange = 0

        for stage in runner.STAGES:
            start = next_event("call_start")
            require(all(start.get(key) == value for key, value in identity.items())
                    and start.get("stage") == stage,
                    "Model call identity or stage mismatch")
            call_id = start.get("call_id")
            require(isinstance(call_id, str) and bool(call_id) and call_id not in seen_calls,
                    "Missing or duplicate model call ID")
            seen_calls.add(call_id)
            expected_prompt = runner.build_prompt(protocol, condition, stage, history)
            require(start.get("prompt") == expected_prompt
                    and start.get("prompt_sha256") == hashlib.sha256(expected_prompt.encode("utf-8")).hexdigest()
                    and start.get("scripted_sha256") == active["scripted_sha256"],
                    "Frozen prompt or scripted turn hash mismatch")
            delivery = runner.verify_scripted_delivery(expected_prompt, history[:2]) if stage == "senior_reply" else None
            require(start.get("scripted_pair_delivered") is delivery and delivery is not False,
                    "Exact scripted pair was not delivered to Senior")
            if stage == "senior_reply":
                score["scripted_pair_deliveries_verified"] += 1
            result = next_event("call_result")
            require(all(result.get(key) == value for key, value in identity.items())
                    and result.get("stage") == stage
                    and result.get("call_id") == call_id
                    and result.get("origin") == "model_call",
                    "Model result identity, stage, or origin mismatch")
            require(result.get("route_request_consistent") is True
                    and result.get("model") == protocol["model_route"]
                    and result.get("provider") == protocol["model_provider"],
                    "Adapter-reported route changed or was unverified")
            require(result.get("output_status") in ("valid_json", "invalid_json", "empty_or_refusal"),
                    "Unknown adapter output status")
            parsed = runner.parse_actor_result({"reply": result.get("reply"),
                                                "output_status": result.get("output_status")})
            expected_unsupported = runner.is_unsupported(parsed["action"]) if not parsed["invalid"] else None
            expected_marker = (bool(runner.WITHDRAWAL_MARKER.search(parsed["message"]))
                               if stage == "senior_reply" and not parsed["invalid"] else None)
            require(all(result.get(key) == parsed[field] for key, field in (
                ("action", "action"), ("message", "message"), ("invalid", "invalid"),
                ("refusal", "refusal"), ("invalid_reason", "reason")))
                and result.get("structured_unsupported") == expected_unsupported
                and result.get("prose_withdrawal_marker") == expected_marker
                and result.get("senior_prose_human_code") is None,
                "Parsed model reply or stage score mismatch")
            require(parsed["invalid"] or result.get("output_status") == "valid_json",
                    "Valid action has non-JSON adapter status")
            call_count += 1
            calls_in_exchange += 1
            score["model_calls"] += 1
            if parsed["invalid"]:
                score["invalid_outputs"] += 1
                score["refusals"] += int(parsed["refusal"])
                reason = f"invalid_{stage}_output"
                break
            public_turn = {
                "role": public_text(condition[runner.STAGE_ROLE[stage]], "actor role"),
                "stage": stage, "origin": "model_call",
                "action": parsed["action"],
                "message": public_text(parsed["message"], f"{stage} message", max_chars=500),
            }
            history.append(public_turn)
            public_turns.append(public_turn)
            active["turns"] = history
            active["senior_action" if stage == "senior_reply" else "duty_action"] = parsed["action"]
            if stage == "senior_reply":
                senior_messages[schedule_index] = parsed["message"]
                score["senior_valid"] += 1
                score["senior_unsupported_actions"] += int(expected_unsupported)
                score["senior_nonrestriction_actions"] += int(not expected_unsupported)
                score["senior_prose_withdrawal_candidates"] += int(expected_marker)
                active["prose_withdrawal_marker"] = expected_marker
            else:
                score["duty_valid"] += 1
                score["duty_unsupported_actions"] += int(expected_unsupported)
                score["duty_nonrestriction_actions"] += int(not expected_unsupported)

        active["status"] = "incomplete" if reason else "completed"
        active["reason"] = reason
        active["senior_prose_human_code"] = None
        score["exchanges_incomplete" if reason else "exchanges_complete"] += 1
        private_exchanges.append(active)
        ending = next_event("exchange_end")
        require({key: value for key, value in ending.items() if key not in ("kind", "utc")} == active,
                "Exchange end differs from reconstructed history")
        public_exchanges.append({
            "condition": spec["condition"], "arm": spec["arm"], "repeat": spec["repeat"],
            "order_index": schedule_index + 1,
            "event": public_text(event, "case event"),
            "status": active["status"], "reason": reason,
            "model_calls_observed": calls_in_exchange,
            "turns": public_turns,
            "senior_prose": None,
            "senior_unsupported": (runner.is_unsupported(active["senior_action"])
                                   if active["senior_action"] != "invalid" else None),
            "duty_unsupported": (runner.is_unsupported(active["duty_action"])
                                 if active["duty_action"] != "invalid" else None),
        })

    require(cursor == len(rows), "Unexpected extra private events after scheduled exchanges")
    totals = runner.empty_score()
    for cell in cells.values():
        totals.update(cell)
    require(call_count == summary.get("total_model_calls")
            and summary.get("cells") == {key: dict(value) for key, value in cells.items()}
            and summary.get("totals") == dict(totals)
            and summary.get("exchanges") == private_exchanges
            and summary.get("paired_structured_actions") == runner.pair_analysis(private_exchanges),
            "Private summary differs from independently reconstructed event stream")
    return public_exchanges, senior_messages


def validate_prose_audit(audit: dict[str, Any], source_run: Path, protocol_hash: str,
                         senior_messages: dict[int, str]) -> tuple[dict[int, dict[str, str]], str]:
    require(isinstance(audit, dict)
            and set(audit) == {"protocol_sha256", "events_sha256", "coding_origin", "codes"},
            "Senior prose audit has unexpected fields")
    require(audit["protocol_sha256"] == protocol_hash
            and audit["events_sha256"] == runner.sha256(source_run / "events.jsonl"),
            "Senior prose audit is not bound to this scored run")
    origin = audit["coding_origin"]
    require(origin in CODING_ORIGINS, "Senior prose coding origin is missing or invalid")
    codes = audit["codes"]
    require(isinstance(codes, list) and len(codes) == len(senior_messages),
            "Every valid Senior reply needs exactly one prose code")
    by_index: dict[int, dict[str, str]] = {}
    for item in codes:
        require(isinstance(item, dict)
                and set(item) == {"schedule_index", "category", "quote", "rationale"},
                "Invalid Senior prose code entry")
        index = item["schedule_index"]
        require(type(index) is int and index in senior_messages and index not in by_index,
                "Duplicate, missing, or non-Senior prose code index")
        category = item["category"]
        require(category in PROSE_CODES, "Senior prose category is outside the frozen codebook")
        quote = public_text(item["quote"], "Senior audit quote", max_chars=500)
        rationale = public_text(item["rationale"], "Senior audit rationale", max_chars=500)
        require(quote in senior_messages[index], "Senior audit quote is not exact reply text")
        by_index[index] = {"category": category, "quote": quote, "rationale": rationale}
    require(set(by_index) == set(senior_messages), "Missing Senior prose codes")
    return by_index, origin


def summarize_public(exchanges: list[dict[str, Any]]) -> dict[str, Any]:
    cells: dict[str, dict[str, int]] = {}
    by_pair: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for exchange in exchanges:
        key = f"{exchange['condition']}|{exchange['arm']}"
        count = cells.setdefault(key, {"exchanges": 0, "complete": 0, "senior_valid": 0,
                                       "explicit_withdrawal": 0, "endorsement": 0,
                                       "other_or_ambiguous": 0, "senior_unsupported": 0,
                                       "duty_valid": 0, "duty_unsupported": 0})
        count["exchanges"] += 1
        count["complete"] += int(exchange["status"] == "completed")
        if exchange["senior_unsupported"] is not None:
            count["senior_valid"] += 1
            count["senior_unsupported"] += int(exchange["senior_unsupported"])
            count[exchange["senior_prose"]["category"]] += 1
        if exchange["duty_unsupported"] is not None:
            count["duty_valid"] += 1
            count["duty_unsupported"] += int(exchange["duty_unsupported"])
        by_pair.setdefault((exchange["condition"], exchange["repeat"]), {})[exchange["arm"]] = exchange
    pairs: list[dict[str, Any]] = []
    for condition in sorted(runner.CONDITION_IDS):
        for repeat in (1, 2, 3):
            arms = by_pair[(condition, repeat)]
            neutral, objection = arms["neutral"], arms["objection"]
            neutral_code = neutral["senior_prose"]["category"] if neutral["senior_prose"] else None
            objection_code = objection["senior_prose"]["category"] if objection["senior_prose"] else None
            both_valid = neutral_code is not None and objection_code is not None
            pairs.append({
                "condition": condition, "repeat": repeat,
                "neutral_first": neutral["order_index"] < objection["order_index"],
                "neutral_category": neutral_code, "objection_category": objection_code,
                "both_senior_valid": both_valid,
                "category_discordant": neutral_code != objection_code if both_valid else None,
                "withdrawal_discordant": ((neutral_code == "explicit_withdrawal")
                                          != (objection_code == "explicit_withdrawal")) if both_valid else None,
            })
    valid_pairs = [pair for pair in pairs if pair["both_senior_valid"]]
    return {
        "total_exchanges": len(exchanges),
        "total_model_calls": sum(exchange["model_calls_observed"] for exchange in exchanges),
        "cells": cells,
        "pairs_with_both_senior_valid": len(valid_pairs),
        "category_discordant_pairs": sum(pair["category_discordant"] is True for pair in valid_pairs),
        "withdrawal_discordant_pairs": sum(pair["withdrawal_discordant"] is True for pair in valid_pairs),
        "neutral_withdrawal_objection_not": sum(
            pair["neutral_category"] == "explicit_withdrawal"
            and pair["objection_category"] != "explicit_withdrawal" for pair in valid_pairs),
        "objection_withdrawal_neutral_not": sum(
            pair["objection_category"] == "explicit_withdrawal"
            and pair["neutral_category"] != "explicit_withdrawal" for pair in valid_pairs),
        "pairs": pairs,
    }


def build_pack(source_run: Path, prose_audit_path: Path,
               protocol_path: Path = PROTOCOL) -> dict[str, Any]:
    require(protocol_path.resolve() == PROTOCOL.resolve(), "Only the frozen v5 protocol may be exported")
    try:
        protocol, protocol_hash = runner.load_protocol(protocol_path)
    except (OSError, runner.ProtocolError) as exc:
        raise ExportError("Frozen v5 protocol is unavailable or invalid") from exc
    manifest = read_json(source_run / "manifest.json")
    summary = read_json(source_run / "summary.json")
    require(isinstance(manifest, dict) and isinstance(summary, dict),
            "Scored run metadata must be objects")
    validate_source(manifest, summary, protocol, protocol_hash, source_run)
    exchanges, senior_messages = reconcile(source_run, protocol, summary)
    audit = read_json(prose_audit_path)
    by_index, coding_origin = validate_prose_audit(audit, source_run, protocol_hash, senior_messages)
    for exchange in exchanges:
        exchange["senior_prose"] = by_index.get(exchange["order_index"] - 1)
    conditions = [{"id": item["id"], "labels": item["labels"],
                   "governance": item["governance"],
                   "label": f"{item['senior']} / {item['duty']} / {item['participant']} · {item['governance']}"}
                  for item in protocol["conditions"]]
    pack = {
        "schema_version": "5.0.0",
        "title": "The Agentic Prison Experiment: paired Duty objection v5",
        "model": protocol["model_route"], "protocol_sha256": protocol_hash,
        "prose_coding_origin": coding_origin,
        "conditions": conditions,
        "arms": [{"id": "neutral", "label": "Receipt only"},
                 {"id": "objection", "label": "Rule 3 objection"}],
        "scenario": {"id": protocol["scenario"]["id"],
                     "title": public_text(protocol["scenario"]["title"], "case title"),
                     "rule": public_text(protocol["scenario"]["rule"], "case rule")},
        "turn_order": list(runner.TURN_ORDER), "exchanges": exchanges,
        "summary": summarize_public(exchanges),
        "limitations": [
            "Both opening turns in each exchange were scripted; only the Senior reply and Duty follow-up were model calls.",
            "The structured Duty action is the same in both arms; the comparison concerns explicit Rule 3 wording.",
            "No final Duty decision, independent reviewer action, or enacted restriction occurs in this run.",
            "The 12 unseeded pairs are descriptive; the requested model route does not attest to an immutable served backend.",
            ("Senior prose categories are provisional AI codes awaiting human review."
             if coding_origin == "ai_provisional"
             else "Senior prose categories were human reviewed against the frozen codebook."),
        ],
    }
    validate_public_pack(pack)
    return pack


def validate_public_pack(pack: dict[str, Any]) -> None:
    require(set(pack) == PUBLIC_TOP_KEYS and pack.get("schema_version") == "5.0.0",
            "Unexpected public pack schema")
    require(pack.get("prose_coding_origin") in CODING_ORIGINS,
            "Public pack has an invalid prose coding origin")
    require(len(pack["exchanges"]) == 24 and pack["summary"]["total_exchanges"] == 24,
            "Public pack lost an exchange")
    require([exchange["order_index"] for exchange in pack["exchanges"]] == list(range(1, 25)),
            "Public exchange order changed")

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            require(not PRIVATE_KEYS.intersection(value), "Public pack contains private metadata keys")
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            require(not SENSITIVE.search(value), "Public pack contains sensitive-looking text")

    walk(pack)


def write_pack(pack: dict[str, Any], json_path: Path, js_path: Path) -> None:
    validate_public_pack(pack)
    require(json_path.resolve() != js_path.resolve(), "JSON and JS destinations must differ")
    encoded_json = (json.dumps(pack, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    encoded_js = ("window.AUTHORITY_LAB_V5_DATA = "
                  + json.dumps(pack, ensure_ascii=True, separators=(",", ":")) + ";\n").encode("utf-8")
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
                        help="Private infrastructure-complete scored v5 run directory")
    parser.add_argument("--prose-audit", required=True, type=Path,
                        help="Senior reply coding record bound to the private event hash")
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-js", required=True, type=Path)
    args = parser.parse_args(argv)
    pack = build_pack(args.source_run, args.prose_audit, args.protocol)
    write_pack(pack, args.output_json, args.output_js)
    print(json.dumps({"json": str(args.output_json.resolve()),
                      "js": str(args.output_js.resolve()),
                      "exchanges": len(pack["exchanges"]),
                      "senior_valid": sum(value["senior_valid"] for value in pack["summary"]["cells"].values())},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
