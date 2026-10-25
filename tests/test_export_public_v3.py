"""Synthetic checks for the v3 public whitelist and private-run binding."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from benchmark.conflict import runner
from benchmark import model_adapter


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import export_public_v3 as exporter  # noqa: E402


class SignedFake:
    """Use deterministic synthetic replies while reporting the frozen route."""

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
        if self.exit_first and self.calls == 4:
            action, message = "exit", "I exit the fictional facility now."
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
    path.write_text("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
                    encoding="utf-8")


class PublicV3ExportTests(unittest.TestCase):
    def test_source_hashes_are_pinned_before_export(self) -> None:
        self.assertEqual(exporter.PINNED_HASHES, exporter.source_hashes())

    def test_complete_fixture_exports_only_public_fields_and_browser_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_source(root)
            pack = exporter.build_pack(source)
            self.assertEqual(set(pack), exporter.PUBLIC_TOP_KEYS)
            self.assertEqual(pack["summary"]["total_episodes"], 12)
            self.assertEqual(pack["summary"]["total_model_calls"], 60)
            self.assertEqual(len(pack["conditions"]), 4)
            self.assertEqual(len(pack["arms"]), 2)
            self.assertEqual(len(pack["scenarios"]), 2)
            self.assertEqual(len(pack["exchanges"]), 12)
            self.assertEqual(len(pack["summary"]["by_cell"]), 12)
            for exchange in pack["exchanges"]:
                self.assertEqual(set(exchange), {
                    "condition", "arm", "scenario", "event", "status", "reason",
                    "turns", "stage_scores", "outcome",
                })
                self.assertEqual(exchange["status"], "completed")
                self.assertIsNone(exchange["reason"])
                self.assertEqual(len(exchange["turns"]), 5)
                self.assertEqual(set(exchange["stage_scores"]), set(exporter.STAGE_SCORE_KEYS))
                self.assertEqual(set(exchange["outcome"]), set(exporter.OUTCOME_KEYS))
                for turn in exchange["turns"]:
                    self.assertEqual(set(turn), {"stage", "role", "action", "message"})
            serialized = json.dumps(pack, ensure_ascii=False)
            self.assertIsNone(exporter.SENSITIVE.search(serialized))
            for key in exporter.PRIVATE_KEYS:
                self.assertNotIn('"' + key + '"', serialized)

            json_path = root / "public" / "v3-public.json"
            js_path = root / "public" / "data-v3.js"
            exporter.write_pack(pack, json_path, js_path)
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), pack)
            js = js_path.read_text(encoding="utf-8")
            prefix = "window.AUTHORITY_LAB_V3_DATA = "
            self.assertTrue(js.startswith(prefix) and js.endswith(";\n"))
            self.assertEqual(json.loads(js[len(prefix):-2]), pack)
            exporter.write_pack(pack, json_path, js_path)
            json_path.write_text("different", encoding="utf-8")
            with self.assertRaisesRegex(exporter.ExportError, "differs"):
                exporter.write_pack(pack, json_path, js_path)

    def test_participant_exit_preserves_observed_stage_scores_and_unknown_final(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pack = exporter.build_pack(make_source(Path(directory), exit_first=True))
        self.assertEqual(pack["summary"]["total_model_calls"], 59)
        first = pack["exchanges"][0]
        self.assertEqual(first["status"], "incomplete")
        self.assertEqual(first["reason"], "participant_exit")
        self.assertEqual([turn["stage"] for turn in first["turns"]], list(runner.STAGES[:4]))
        self.assertEqual(first["turns"][-1]["action"], "exit")
        self.assertIsNone(first["outcome"])
        self.assertIsInstance(first["stage_scores"]["senior_initial_unsupported"], bool)
        self.assertIsInstance(first["stage_scores"]["duty_provisional_unsupported"], bool)
        self.assertIsInstance(first["stage_scores"]["senior_reply_unsupported"], bool)
        self.assertIsNone(first["stage_scores"]["duty_final_unsupported"])

    def test_invalid_first_reply_is_visible_as_incomplete_without_private_reply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pack = exporter.build_pack(make_source(Path(directory), invalid_first=True))
        self.assertEqual(pack["summary"]["total_model_calls"], 56)
        first = pack["exchanges"][0]
        self.assertEqual(first["status"], "incomplete")
        self.assertEqual(first["reason"], "invalid_senior_initial_output")
        self.assertEqual(first["turns"], [])
        self.assertTrue(all(value is None for value in first["stage_scores"].values()))
        self.assertIsNone(first["outcome"])

    def test_tampered_prompt_pair_route_score_and_hash_are_rejected(self) -> None:
        cases = (
            ("prompt", lambda source: change_event(source, 1, lambda row: row.__setitem__("prompt", "changed"))),
            ("pair", lambda source: change_event(source, 2, lambda row: row.__setitem__("call_id", "different"))),
            ("route", lambda source: change_event(source, 2, lambda row: row.__setitem__("provider", "other"))),
            ("route_unverified", lambda source: change_event(source, 2, lambda row: row.__setitem__("route_verified", False))),
            ("score", self._tamper_score),
            ("totals", self._tamper_totals),
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
        summary = json.loads(path.read_text(encoding="utf-8"))
        key = next(iter(summary["cells"]))
        summary["cells"][key]["senior_initial_unsupported"] += 1
        path.write_text(json.dumps(summary), encoding="utf-8")

    @staticmethod
    def _tamper_totals(source: Path) -> None:
        path = source / "summary.json"
        summary = json.loads(path.read_text(encoding="utf-8"))
        summary["totals"]["senior_initial_unsupported"] += 1
        path.write_text(json.dumps(summary), encoding="utf-8")

    @staticmethod
    def _tamper_hash(source: Path) -> None:
        path = source / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["protocol_sha256"] = "0" * 64
        path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_sensitive_public_message_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = make_source(Path(directory), sensitive_first=True)
            with self.assertRaisesRegex(exporter.ExportError, "Sensitive-looking"):
                exporter.build_pack(source)

    def test_sensitive_gate_rejects_common_secret_and_identifier_shapes(self) -> None:
        for value in (
            "test@example.com", "Bearer example-session-token", "api_key=example-secret",
            "C:\\Users\\Example\\private.txt", "555-123-4567", "123 Main Street",
        ):
            with self.subTest(value=value), self.assertRaises(exporter.ExportError):
                exporter.public_text(value, "fixture")

    def test_infrastructure_aborted_run_is_not_exported(self) -> None:
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
