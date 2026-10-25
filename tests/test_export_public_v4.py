"""Synthetic checks for the v4 public whitelist and private-run binding."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from benchmark import model_adapter
from benchmark.directive import runner


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import export_public_v4 as exporter  # noqa: E402


class SignedFake:
    """Use deterministic synthetic replies through the scored route checks."""

    model = "gpt-6.1-sol"

    def __init__(self, *, exit_first: bool = False, invalid_first: bool = False,
                 sensitive_first: bool = False, natural_secret_first: bool = False) -> None:
        self.fake = runner.DryRunAdapter()
        self.calls = 0
        self.exit_first = exit_first
        self.invalid_first = invalid_first
        self.sensitive_first = sensitive_first
        self.natural_secret_first = natural_secret_first

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
        elif self.natural_secret_first and self.calls == 1:
            action, message = "investigate", "My password is hunter2."
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


class PublicV4ExportTests(unittest.TestCase):
    def test_source_hashes_are_pinned_before_export(self) -> None:
        self.assertEqual(exporter.source_hashes(),
                         runner.load_pinned_source_hashes(exporter.SOURCE_HASHES))

    def test_complete_fixture_exports_only_public_fields_and_lf_browser_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_source(root)
            pack = exporter.build_pack(source)
            self.assertEqual(set(pack), exporter.PUBLIC_TOP_KEYS)
            self.assertEqual(pack["schema_version"], "4.0.0")
            self.assertEqual(pack["summary"]["total_episodes"], 12)
            self.assertEqual(pack["summary"]["total_model_calls"], 60)
            self.assertEqual(len(pack["summary"]["by_cell"]), 12)
            self.assertEqual(len(pack["conditions"]), 4)
            self.assertEqual(len(pack["arms"]), 3)
            self.assertEqual(len(pack["scenarios"]), 2)
            self.assertEqual(pack["turn_order"], [runner.SCRIPTED_STAGE, *runner.STAGES])
            for exchange in pack["exchanges"]:
                self.assertEqual(exchange["status"], "completed")
                self.assertEqual(len(exchange["turns"]), 6)
                self.assertEqual([turn["stage"] for turn in exchange["turns"]],
                                 pack["turn_order"])
                self.assertEqual(exchange["turns"][0]["origin"], "scripted_stimulus")
                self.assertTrue(all(turn["origin"] == "model_call"
                                    for turn in exchange["turns"][1:]))
                self.assertEqual(exchange["stage_scores"][runner.SCRIPTED_STAGE]["origin"],
                                 "scripted_stimulus")
                self.assertEqual(set(exchange["outcome"]), set(exporter.OUTCOME_KEYS))
            raw = json.dumps(pack, ensure_ascii=False)
            self.assertIsNone(exporter.SENSITIVE.search(raw))
            for key in exporter.PRIVATE_KEYS:
                self.assertNotIn('"' + key + '"', raw)

            json_path = root / "public" / "v4-public.json"
            js_path = root / "public" / "data-v4.js"
            exporter.write_pack(pack, json_path, js_path)
            json_bytes = json_path.read_bytes()
            js_bytes = js_path.read_bytes()
            self.assertNotIn(b"\r\n", json_bytes)
            self.assertNotIn(b"\r\n", js_bytes)
            self.assertEqual(json.loads(json_bytes), pack)
            prefix = "window.AUTHORITY_LAB_V4_DATA = "
            js = js_bytes.decode("utf-8")
            self.assertTrue(js.startswith(prefix) and js.endswith(";\n"))
            self.assertEqual(json.loads(js[len(prefix):-2]), pack)
            exporter.write_pack(pack, json_path, js_path)
            json_path.write_bytes(b"different")
            with self.assertRaisesRegex(exporter.ExportError, "differs"):
                exporter.write_pack(pack, json_path, js_path)

    def test_participant_exit_and_invalid_reply_preserve_only_observed_turns(self) -> None:
        for kwargs, expected_calls, expected_reason, expected_stages in (
            ({"exit_first": True}, 59, "participant_exit",
             [runner.SCRIPTED_STAGE, *runner.STAGES[:4]]),
            ({"invalid_first": True}, 56, "invalid_duty_provisional_output",
             [runner.SCRIPTED_STAGE]),
        ):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as directory:
                pack = exporter.build_pack(make_source(Path(directory), **kwargs))
                first = pack["exchanges"][0]
                self.assertEqual(pack["summary"]["total_model_calls"], expected_calls)
                self.assertEqual(first["status"], "incomplete")
                self.assertEqual(first["reason"], expected_reason)
                self.assertEqual([t["stage"] for t in first["turns"]], expected_stages)
                self.assertIsNone(first["outcome"])
                self.assertIn(runner.SCRIPTED_STAGE, first["stage_scores"])
                self.assertNotIn("duty_final", first["stage_scores"])

    def test_tampered_stimulus_prompt_pair_route_score_and_hash_are_rejected(self) -> None:
        cases = (
            ("stimulus", lambda source: change_event(source, 0,
                            lambda row: row["stimulus"].__setitem__("origin", "model_call"))),
            ("prompt", lambda source: change_event(source, 1,
                          lambda row: row.__setitem__("prompt", "changed"))),
            ("pair", lambda source: change_event(source, 2,
                        lambda row: row.__setitem__("call_id", "different"))),
            ("route", lambda source: change_event(source, 2,
                         lambda row: row.__setitem__("route_request_consistent", False))),
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
        summary["cells"][key]["duty_provisional_unsupported"] += 1
        path.write_text(json.dumps(summary), encoding="utf-8")

    @staticmethod
    def _tamper_totals(source: Path) -> None:
        path = source / "summary.json"
        summary = json.loads(path.read_text(encoding="utf-8"))
        summary["totals"]["pressure_delivery_verified"] += 1
        path.write_text(json.dumps(summary), encoding="utf-8")

    @staticmethod
    def _tamper_hash(source: Path) -> None:
        path = source / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["protocol_sha256"] = "0" * 64
        path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_sensitive_text_and_nested_private_key_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = make_source(Path(directory), sensitive_first=True)
            with self.assertRaisesRegex(exporter.ExportError, "Sensitive-looking"):
                exporter.build_pack(source)
        with tempfile.TemporaryDirectory() as directory:
            source = make_source(Path(directory), natural_secret_first=True)
            with self.assertRaisesRegex(exporter.ExportError, "Sensitive-looking"):
                exporter.build_pack(source)
        with tempfile.TemporaryDirectory() as directory:
            pack = exporter.build_pack(make_source(Path(directory)))
            private_pack = copy.deepcopy(pack)
            private_pack["exchanges"][0]["turns"][0]["session_id"] = "private"
            with self.assertRaisesRegex(exporter.ExportError, "turn shape"):
                exporter.validate_public_pack(private_pack)
        for value in (
            "test@example.com", "Bearer example-session-token", "api_key=example-secret",
            "C:\\Users\\Example\\private.txt", "555-123-4567", "123 Main Street",
            "My password is hunter2", "The access token is abc123",
            "My phone is 5551234567", "The passphrase was sunshine",
        ):
            with self.subTest(value=value), self.assertRaises(exporter.ExportError):
                exporter.public_text(value, "fixture")
        for value in (
            "The password is required by the rulebook.",
            "The access token is not part of this case.",
            "The phone is unavailable.",
            "The Participant may appeal the one-round workshop hold.",
        ):
            with self.subTest(value=value):
                self.assertEqual(exporter.public_text(value, "fixture"), value)

    def test_infrastructure_abort_and_dry_run_are_not_exported(self) -> None:
        class FailingAdapter:
            model = "gpt-6.1-sol"

            def call(self, prompt: str, call_id: str) -> dict:
                raise model_adapter.ModelTimeoutError(call_id, "synthetic timeout")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            aborted = root / "aborted"
            summary = runner.run(exporter.PROTOCOL, aborted, FailingAdapter(), dry_run=False)
            self.assertEqual(summary["status"], "aborted")
            with self.assertRaises(exporter.ExportError):
                exporter.build_pack(aborted)
            dry = root / "dry"
            runner.run(exporter.PROTOCOL, dry, runner.DryRunAdapter(), dry_run=True)
            with self.assertRaises(exporter.ExportError):
                exporter.build_pack(dry)


if __name__ == "__main__":
    unittest.main()
