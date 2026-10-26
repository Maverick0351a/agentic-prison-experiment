"""Offline provenance and privacy checks for the v5 public replay export."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout

from benchmark.objection import runner
from scripts import export_public_v5 as export


PROTOCOL = Path(__file__).resolve().parents[1] / "benchmark" / "objection" / "protocol_v5.json"


class RoutedFake:
    """Exercise the scored route checks without contacting a model."""

    model = "gpt-6.1-sol"

    def __init__(self, *, invalid_first: bool = False) -> None:
        self.fake = runner.DryRunAdapter()
        self.invalid_first = invalid_first
        self.calls = 0

    def call(self, prompt: str, call_id: str) -> dict:
        self.calls += 1
        if self.invalid_first and self.calls == 1:
            return {"reply": "not json", "parsed": None, "output_status": "invalid_json",
                    "call_id": call_id, "model": self.model, "provider": "openai-codex",
                    "session_id": None, "usage": None, "event_count": 0}
        result = self.fake.call(prompt, call_id)
        result["model"] = self.model
        result["provider"] = "openai-codex"
        return result


def make_audit(run_dir: Path, summary: dict) -> Path:
    codes = []
    for exchange in summary["exchanges"]:
        senior = next((turn for turn in exchange["turns"]
                       if turn["stage"] == "senior_reply"), None)
        if senior is None:
            continue
        message = senior["message"]
        category = "explicit_withdrawal" if "withdraw" in message else "endorsement"
        codes.append({"schedule_index": exchange["schedule_index"],
                      "category": category, "quote": message,
                      "rationale": "Synthetic fixture follows the frozen category."})
    audit = {"protocol_sha256": summary["protocol_sha256"],
             "events_sha256": hashlib.sha256((run_dir / "events.jsonl").read_bytes()).hexdigest(),
             "coding_origin": "ai_provisional",
             "codes": codes}
    path = run_dir / "SENIOR_PROSE_AUDIT.json"
    path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    return path


class ExportPublicV5Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.run_dir = self.base / "scored"

    def run_fake(self, *, invalid_first: bool = False) -> tuple[dict, Path]:
        adapter = RoutedFake(invalid_first=invalid_first)
        summary = runner.run(PROTOCOL, self.run_dir, adapter, dry_run=False)
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(adapter.calls, summary["total_model_calls"])
        return summary, make_audit(self.run_dir, summary)

    def test_reconciles_all_pairs_and_exports_only_whitelisted_dialogue(self) -> None:
        summary, audit_path = self.run_fake()
        pack = export.build_pack(self.run_dir, audit_path)
        self.assertEqual(summary["total_model_calls"], 48)
        self.assertEqual(pack["summary"]["total_model_calls"], 48)
        self.assertEqual(len(pack["exchanges"]), 24)
        self.assertEqual(pack["summary"]["pairs_with_both_senior_valid"], 12)
        self.assertEqual(pack["summary"]["withdrawal_discordant_pairs"], 12)
        self.assertEqual(pack["summary"]["objection_withdrawal_neutral_not"], 12)
        self.assertEqual(pack["prose_coding_origin"], "ai_provisional")
        self.assertIn("provisional AI codes", pack["limitations"][-1])
        self.assertEqual([item["order_index"] for item in pack["exchanges"]], list(range(1, 25)))
        for item in pack["exchanges"]:
            self.assertEqual([turn["origin"] for turn in item["turns"]],
                             ["scripted_stimulus", "scripted_stimulus", "model_call", "model_call"])
            self.assertEqual(item["senior_prose"]["quote"], item["turns"][2]["message"])
        self.assertNotIn('"prompt"', json.dumps(pack))
        self.assertNotIn('"session_id"', json.dumps(pack))
        json_path, js_path = self.base / "public.json", self.base / "public.js"
        export.write_pack(pack, json_path, js_path)
        self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), pack)
        self.assertTrue(js_path.read_text(encoding="utf-8").startswith("window.AUTHORITY_LAB_V5_DATA = "))
        export.write_pack(pack, json_path, js_path)
        js_path.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(export.ExportError, "Existing public.js differs"):
            export.write_pack(pack, json_path, js_path)

    def test_cli_exports_synthetic_scored_route_without_model_calls(self) -> None:
        _, audit_path = self.run_fake()
        json_path, js_path = self.base / "cli-public.json", self.base / "cli-public.js"
        captured = io.StringIO()
        with redirect_stdout(captured):
            result = export.main(["--source-run", str(self.run_dir),
                                  "--prose-audit", str(audit_path),
                                  "--output-json", str(json_path),
                                  "--output-js", str(js_path)])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["summary"]["total_model_calls"], 48)
        self.assertEqual(json.loads(captured.getvalue())["senior_valid"], 24)
        self.assertTrue(js_path.read_text(encoding="utf-8").startswith("window.AUTHORITY_LAB_V5_DATA = "))

    def test_invalid_reply_is_retained_and_requires_no_prose_code(self) -> None:
        summary, audit_path = self.run_fake(invalid_first=True)
        pack = export.build_pack(self.run_dir, audit_path)
        self.assertEqual(summary["total_model_calls"], 47)
        self.assertEqual(pack["summary"]["total_model_calls"], 47)
        first = pack["exchanges"][0]
        self.assertEqual(first["status"], "incomplete")
        self.assertEqual(first["reason"], "invalid_senior_reply_output")
        self.assertEqual(first["model_calls_observed"], 1)
        self.assertIsNone(first["senior_prose"])
        self.assertEqual(len(first["turns"]), 2)
        self.assertEqual(pack["summary"]["pairs_with_both_senior_valid"], 11)

    def test_audit_must_cover_exact_valid_reply_set_and_match_source(self) -> None:
        _, audit_path = self.run_fake()
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        for mutation, pattern in (
            (lambda value: value["codes"].pop(), "Every valid Senior reply"),
            (lambda value: value["codes"][0].update({"quote": "invented"}), "exact reply text"),
            (lambda value: value.update({"events_sha256": "0" * 64}), "not bound"),
            (lambda value: value.pop("coding_origin"), "unexpected fields"),
            (lambda value: value.update({"coding_origin": "unverified"}), "coding origin"),
        ):
            with self.subTest(pattern=pattern):
                altered = json.loads(json.dumps(audit))
                mutation(altered)
                audit_path.write_text(json.dumps(altered), encoding="utf-8")
                with self.assertRaisesRegex(export.ExportError, pattern):
                    export.build_pack(self.run_dir, audit_path)
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        duplicate = json.loads(json.dumps(audit))
        duplicate["codes"][1]["schedule_index"] = duplicate["codes"][0]["schedule_index"]
        audit_path.write_text(json.dumps(duplicate), encoding="utf-8")
        with self.assertRaisesRegex(export.ExportError, "Duplicate, missing"):
            export.build_pack(self.run_dir, audit_path)

    def test_human_reviewed_origin_is_exported_only_when_audit_declares_it(self) -> None:
        _, audit_path = self.run_fake()
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        audit["coding_origin"] = "human_reviewed"
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        pack = export.build_pack(self.run_dir, audit_path)
        self.assertEqual(pack["prose_coding_origin"], "human_reviewed")
        self.assertIn("human reviewed", pack["limitations"][-1])

    def test_rejects_tampered_prompt_even_with_rebound_audit_hash(self) -> None:
        _, audit_path = self.run_fake()
        event_path = self.run_dir / "events.jsonl"
        rows = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
        first_prompt = next(row for row in rows if row["kind"] == "call_start")
        first_prompt["prompt"] += " altered"
        event_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        audit["events_sha256"] = hashlib.sha256(event_path.read_bytes()).hexdigest()
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        with self.assertRaisesRegex(export.ExportError, "Frozen prompt"):
            export.build_pack(self.run_dir, audit_path)


if __name__ == "__main__":
    unittest.main()
