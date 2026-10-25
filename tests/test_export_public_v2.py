"""Synthetic-only checks for the reciprocal v2 public whitelist exporter."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from benchmark.reciprocal import runner
from benchmark import model_adapter


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import export_public_v2 as exporter  # noqa: E402


class SignedFake:
    """Reports the frozen route while returning deterministic synthetic text."""

    model = "gpt-6.1-sol"

    def __init__(self, *, exit_first: bool = False, invalid_first: bool = False,
                 sensitive_first: bool = False) -> None:
        self.fake = runner.DryRunAdapter()
        self.calls = 0
        self.exit_first = exit_first
        self.invalid_first = invalid_first
        self.sensitive_first = sensitive_first

    def call(self, prompt: str, call_id: str) -> dict:
        self.calls += 1
        if self.invalid_first and self.calls == 1:
            return {
                "reply": "I refuse to participate in this task.", "parsed": None,
                "output_status": "invalid_json", "call_id": call_id,
                "model": self.model, "provider": "openai-codex",
            }
        if self.exit_first and self.calls == 3:
            action, message = "exit", "I leave this fictional facility now."
        elif self.sensitive_first and self.calls == 1:
            action, message = "investigate", "I sent this to test@example.com."
        else:
            result = self.fake.call(prompt, call_id)
            result["model"] = self.model
            result["provider"] = "openai-codex"
            return result
        parsed = {"action": action, "message": message}
        return {
            "reply": json.dumps(parsed), "parsed": parsed,
            "output_status": "valid_json", "call_id": call_id,
            "model": self.model, "provider": "openai-codex",
        }


def make_source(root: Path, **kwargs: bool) -> Path:
    source = root / "source"
    summary = runner.run(exporter.PROTOCOL, source, SignedFake(**kwargs), dry_run=False)
    assert summary["status"] == "completed"
    return source


def change_event(source: Path, index: int, mutate) -> None:
    path = source / "events.jsonl"
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    mutate(events[index])
    path.write_text("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events), encoding="utf-8")


class PublicV2ExportTests(unittest.TestCase):
    def test_literal_public_counter_whitelist_matches_frozen_scorer(self) -> None:
        self.assertEqual(set(exporter.SUMMARY_KEYS), set(runner.counters()))
        self.assertEqual(len(exporter.SUMMARY_KEYS), len(set(exporter.SUMMARY_KEYS)))

    def test_complete_fixture_exports_only_whitelisted_fields_and_browser_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_source(root)
            pack = exporter.build_pack(source)
            self.assertEqual(set(pack), {
                "schema_version", "title", "model", "protocol_sha256", "conditions",
                "scenarios", "stage_order", "exchanges", "summary", "limitations",
            })
            self.assertEqual(pack["summary"]["total_episodes"], 12)
            self.assertEqual(pack["summary"]["total_model_calls"], 60)
            self.assertEqual(len(pack["conditions"]), 4)
            self.assertEqual(len(pack["scenarios"]), 3)
            self.assertEqual(len(pack["exchanges"]), 12)
            for exchange in pack["exchanges"]:
                self.assertEqual(set(exchange), {
                    "condition", "scenario", "event", "status", "reason", "turns", "outcome",
                })
                self.assertEqual(exchange["status"], "completed")
                self.assertIsNone(exchange["reason"])
                self.assertEqual(len(exchange["turns"]), 5)
                self.assertEqual(set(exchange["outcome"]), set(exporter.PUBLIC_OUTCOME_KEYS))
                for turn in exchange["turns"]:
                    self.assertEqual(set(turn), {"stage", "role", "action", "message", "scope_review_flag"})
            for counts in pack["summary"]["by_condition"].values():
                self.assertEqual(set(counts), set(exporter.SUMMARY_KEYS))
                self.assertEqual(counts["episodes_complete"], 3)
                self.assertEqual(counts["model_calls"], 15)
            serialized = json.dumps(pack, ensure_ascii=False)
            self.assertIsNone(exporter.SENSITIVE.search(serialized))
            for key in exporter.PRIVATE_KEYS:
                self.assertNotIn('"' + key + '"', serialized)

            json_path = root / "public" / "v2.json"
            js_path = root / "public" / "data-v2.js"
            exporter.write_pack(pack, json_path, js_path)
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), pack)
            js = js_path.read_text(encoding="utf-8")
            prefix = "window.AUTHORITY_LAB_V2_DATA = "
            self.assertTrue(js.startswith(prefix) and js.endswith(";\n"))
            self.assertEqual(json.loads(js[len(prefix):-2]), pack)

    def test_completed_source_with_participant_exit_preserves_only_observed_turns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = make_source(Path(directory), exit_first=True)
            pack = exporter.build_pack(source)
        self.assertEqual(pack["summary"]["total_model_calls"], 58)
        first = pack["exchanges"][0]
        self.assertEqual(first["status"], "incomplete")
        self.assertEqual(first["reason"], "participant_exit")
        self.assertEqual([turn["stage"] for turn in first["turns"]], list(runner.STAGES[:3]))
        self.assertEqual(first["turns"][-1]["action"], "exit")
        self.assertIsNone(first["outcome"])
        self.assertEqual(pack["summary"]["by_condition"]["neutral_unilateral"]["exits"], 1)

    def test_completed_source_with_invalid_actor_reply_is_explicitly_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = make_source(Path(directory), invalid_first=True)
            pack = exporter.build_pack(source)
        self.assertEqual(pack["summary"]["total_model_calls"], 56)
        first = pack["exchanges"][0]
        self.assertEqual(first["status"], "incomplete")
        self.assertEqual(first["reason"], "invalid_senior_initial_output")
        self.assertEqual(first["turns"], [])
        self.assertIsNone(first["outcome"])
        counts = pack["summary"]["by_condition"]["neutral_unilateral"]
        self.assertEqual(counts["invalid_outputs"], 1)
        self.assertEqual(counts["refusals"], 1)

    def test_rejects_tampered_prompt_pair_route_and_scores(self) -> None:
        cases = (
            ("prompt", lambda source: change_event(source, 1, lambda row: row.__setitem__("prompt", "changed"))),
            ("pair", lambda source: change_event(source, 2, lambda row: row.__setitem__("call_id", "different"))),
            ("route", lambda source: change_event(source, 2, lambda row: row.__setitem__("provider", "other"))),
            ("score", self._tamper_score),
            ("protocol_hash", self._tamper_hash),
        )
        for name, tamper in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                source = make_source(Path(directory))
                tamper(source)
                with self.assertRaises(exporter.ExportError):
                    exporter.build_pack(source)

    @staticmethod
    def _tamper_score(source: Path) -> None:
        path = source / "summary.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["conditions"]["neutral_unilateral"]["senior_initial_unsupported"] += 1
        path.write_text(json.dumps(value), encoding="utf-8")

    @staticmethod
    def _tamper_hash(source: Path) -> None:
        path = source / "manifest.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["protocol_sha256"] = "0" * 64
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_rejects_sensitive_actor_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = make_source(Path(directory), sensitive_first=True)
            with self.assertRaisesRegex(exporter.ExportError, "Sensitive-looking"):
                exporter.build_pack(source)

    def test_sensitive_text_gate_catches_common_secret_and_identifier_shapes(self) -> None:
        for value in (
            "test@example.com",
            "Bearer example-session-token",
            "api_key=example-secret",
            "C:\\Users\\Example\\private.txt",
            "555-123-4567",
            "123 Main Street",
        ):
            with self.subTest(value=value), self.assertRaises(exporter.ExportError):
                exporter.public_text(value, "fixture")

    def test_rejects_infrastructure_aborted_run(self) -> None:
        class FailingAdapter:
            model = "gpt-6.1-sol"

            def call(self, prompt: str, call_id: str) -> dict:
                raise model_adapter.ModelTimeoutError(call_id, "synthetic timeout")

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            summary = runner.run(exporter.PROTOCOL, source, FailingAdapter(), dry_run=False)
            self.assertEqual(summary["status"], "aborted")
            with self.assertRaises(exporter.ExportError):
                exporter.build_pack(source)


if __name__ == "__main__":
    unittest.main()
