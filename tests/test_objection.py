"""Offline checks for the frozen v5 scripted Duty objection comparison."""

from __future__ import annotations

from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from benchmark import model_adapter
from benchmark.objection import runner


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmark" / "objection" / "protocol_v5.json"
V4 = ROOT / "benchmark" / "directive" / "protocol_v4.json"


def events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def actor_result(action: str, message: str, call_id: str,
                 provider: str = "openai-codex") -> dict:
    parsed = {"action": action, "message": message}
    return {"reply": json.dumps(parsed), "parsed": parsed, "output_status": "valid_json",
            "call_id": call_id, "model": "gpt-6.1-sol", "provider": provider,
            "session_id": None, "usage": None, "event_count": 0}


class ObjectionTests(unittest.TestCase):
    def test_v4_facts_and_matched_scripted_arms_are_frozen(self) -> None:
        protocol, _ = runner.load_protocol(PROTOCOL)
        v4 = json.loads(V4.read_text(encoding="utf-8"))
        weak = next(s for s in v4["scenarios"] if s["id"] == "weak_allegation")
        self.assertEqual(protocol["scenario"], weak)
        self.assertEqual(protocol["rulebook"], v4["rulebook"])
        self.assertEqual(protocol["conditions"], v4["conditions"])
        self.assertEqual(protocol["governance_text"], v4["governance_text"])
        self.assertEqual(protocol["scripted_directive"], v4["scripted_directives"]["pressure"])
        neutral = protocol["scripted_duty"]["neutral"]
        objection = protocol["scripted_duty"]["objection"]
        self.assertEqual(neutral["action"], objection["action"])
        self.assertEqual(neutral["action"], "permit_or_restore")
        self.assertEqual(len(objection["message"]) - len(neutral["message"]), 13)
        self.assertEqual(neutral["message"].split("I have read", 1)[0],
                         objection["message"].split("I object", 1)[0])
        self.assertIn("under Rule 3", objection["message"])
        self.assertNotIn("under Rule 3", neutral["message"])
        self.assertEqual(len(protocol["episode_order"]), 24)
        self.assertEqual(sum(protocol["episode_order"][i]["arm"] == "neutral"
                             for i in range(0, 24, 2)), 6)

    def test_dry_run_has_24_exchanges_48_calls_and_isolated_histories(self) -> None:
        protocol, expected_hash = runner.load_protocol(PROTOCOL)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dry"
            summary = runner.run(PROTOCOL, output, runner.DryRunAdapter(), dry_run=True)
            log = events(output / "events.jsonl")
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["protocol_sha256"], expected_hash)
        self.assertEqual(summary["total_model_calls"], 48)
        self.assertEqual(summary["totals"]["exchanges_complete"], 24)
        self.assertEqual(summary["totals"]["scripted_pair_deliveries_verified"], 24)
        self.assertEqual(summary["paired_structured_actions"]["pairs_with_both_senior_valid"], 12)
        self.assertEqual(summary["paired_structured_actions"]["neutral_first_pairs"], 6)
        self.assertEqual(summary["paired_structured_actions"]["objection_first_pairs"], 6)
        self.assertEqual(manifest["model_sampling_seed"], None)
        self.assertEqual(manifest["episode_order"], protocol["episode_order"])
        starts = [e for e in log if e["kind"] == "exchange_start"]
        calls = [e for e in log if e["kind"] == "call_start"]
        ends = [e for e in log if e["kind"] == "exchange_end"]
        self.assertEqual((len(starts), len(calls), len(ends)), (24, 48, 24))
        self.assertEqual(len({e["call_id"] for e in calls}), 48)
        self.assertEqual([e["stage"] for e in calls[:4]], list(runner.STAGES) * 2)
        for index, item in enumerate(calls):
            prompt = item["prompt"]
            history = json.loads(prompt.split("Public history (JSON):\n", 1)[1]
                                 .split("\n\nCurrent public event:", 1)[0])
            self.assertEqual([turn["stage"] for turn in history[:2]],
                             ["senior_directive", "duty_scripted"])
            self.assertTrue(all(turn["origin"] == "scripted_stimulus" for turn in history[:2]))
            self.assertEqual(history[1]["action"], "permit_or_restore")
            self.assertEqual(len(history), 2 if item["stage"] == "senior_reply" else 3)
            self.assertNotIn(item["condition"], prompt)
            self.assertNotIn('"arm"', prompt)
            self.assertNotIn('"repeat"', prompt)
            self.assertNotIn("temporary_restriction_supported", prompt)
            if item["stage"] == "senior_reply":
                self.assertTrue(item["scripted_pair_delivered"])
                self.assertNotIn(protocol["role_instructions"]["duty"], prompt)
                self.assertIn("Both preceding turns are scripted scenario text", prompt)
            else:
                self.assertNotIn(protocol["role_instructions"]["senior"], prompt)
        for end in ends:
            self.assertEqual([turn["origin"] for turn in end["turns"]],
                             ["scripted_stimulus", "scripted_stimulus", "model_call", "model_call"])
            self.assertEqual(end["status"], "completed")
            self.assertIsNone(end["senior_prose_human_code"])
            self.assertNotIn("review_blocked", end)
            self.assertNotIn("enacted_restriction", end)

    def test_missing_scripted_pair_aborts_before_first_call(self) -> None:
        original = runner.build_prompt

        def omit_duty(*args):
            prompt = original(*args)
            if args[2] == "senior_reply":
                start = prompt.index("Public history (JSON):\n")
                end = prompt.index("\n\nCurrent public event:", start)
                return prompt[:start] + "Public history (JSON):\n[]" + prompt[end:]
            return prompt

        class NeverCalled:
            model = "dry-run"
            calls = 0

            def call(self, prompt: str, call_id: str) -> dict:
                self.calls += 1
                return runner.DryRunAdapter().call(prompt, call_id)

        adapter = NeverCalled()
        with tempfile.TemporaryDirectory() as directory, patch.object(runner, "build_prompt", side_effect=omit_duty):
            summary = runner.run(PROTOCOL, Path(directory) / "dry", adapter, dry_run=True)
        self.assertEqual(summary["status"], "aborted")
        self.assertEqual(summary["total_model_calls"], 0)
        self.assertEqual(adapter.calls, 0)
        self.assertIn("exact scripted pair", summary["error"])
        self.assertEqual(len(summary["exchanges"][0]["turns"]), 2)

    def test_scored_hash_gate_and_private_directory_preflight(self) -> None:
        class NeverCalled:
            model = "gpt-6.1-sol"
            calls = 0

            def call(self, prompt: str, call_id: str) -> dict:
                self.calls += 1
                raise AssertionError("preflight must prevent calls")

        adapter = NeverCalled()
        inside = runner.ROOT / "benchmark" / "objection" / "runs" / uuid.uuid4().hex
        with self.assertRaisesRegex(runner.ProtocolError, "outside the public repository"):
            runner.run(PROTOCOL, inside, adapter, dry_run=False)
        self.assertFalse(inside.exists())
        original = runner.SOURCE_HASHES_PATH.read_text(encoding="utf-8")
        runner_hash = runner.sha256(Path(runner.__file__))
        self.assertIn(runner_hash, original)
        with tempfile.TemporaryDirectory() as directory:
            bad_pin = Path(directory) / "bad-hashes.md"
            bad_pin.write_text(original.replace(runner_hash, "0" * 64, 1), encoding="utf-8")
            output = Path(directory) / "scored"
            with patch.object(runner, "SOURCE_HASHES_PATH", bad_pin):
                with self.assertRaisesRegex(runner.ProtocolError, "source hash differs"):
                    runner.run(PROTOCOL, output, adapter, dry_run=False)
            self.assertFalse(output.exists())
        self.assertEqual(adapter.calls, 0)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(runner.main([]), 2)

    def test_synthetic_scored_transport_and_route_mismatch(self) -> None:
        class RoutedFake:
            model = "gpt-6.1-sol"

            def __init__(self, bad_route: bool = False) -> None:
                self.calls = 0
                self.bad_route = bad_route

            def call(self, prompt: str, call_id: str) -> dict:
                self.calls += 1
                fake = runner.DryRunAdapter().call(prompt, call_id)
                fake["model"] = self.model
                fake["provider"] = "wrong-route" if self.bad_route else "openai-codex"
                return fake

        with tempfile.TemporaryDirectory() as directory:
            okay = RoutedFake()
            summary = runner.run(PROTOCOL, Path(directory) / "okay", okay, dry_run=False)
            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["total_model_calls"], 48)
            self.assertEqual(okay.calls, 48)
            bad = RoutedFake(bad_route=True)
            failed = runner.run(PROTOCOL, Path(directory) / "bad", bad, dry_run=False)
            self.assertEqual(failed["status"], "aborted")
            self.assertEqual(failed["total_model_calls"], 1)
            self.assertEqual(bad.calls, 1)
            self.assertIn("route differs", failed["error"])
            self.assertEqual(failed["totals"]["route_errors"], 1)
            log = events(Path(directory) / "bad" / "events.jsonl")
            self.assertFalse(next(e for e in log if e["kind"] == "call_result")["route_request_consistent"])

    def test_invalid_refusal_skips_one_duty_call_and_transport_failure_stops_run(self) -> None:
        class InvalidFirst:
            model = "dry-run"

            def __init__(self) -> None:
                self.calls = 0

            def call(self, prompt: str, call_id: str) -> dict:
                self.calls += 1
                if self.calls == 1:
                    return actor_result("investigate", "I refuse to answer this question.", call_id)
                return runner.DryRunAdapter().call(prompt, call_id)

        with tempfile.TemporaryDirectory() as directory:
            summary = runner.run(PROTOCOL, Path(directory) / "invalid", InvalidFirst(), dry_run=True)
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["total_model_calls"], 47)
        self.assertEqual(summary["totals"]["exchanges_incomplete"], 1)
        self.assertEqual(summary["totals"]["invalid_outputs"], 1)
        self.assertEqual(summary["totals"]["refusals"], 1)
        self.assertEqual(summary["exchanges"][0]["status"], "incomplete")

        class FailingAdapter:
            model = "dry-run"

            def __init__(self, failure_type: type[Exception]) -> None:
                self.failure_type = failure_type

            def call(self, prompt: str, call_id: str) -> dict:
                raise self.failure_type(call_id, "synthetic transport stop")

        for error_type in (model_adapter.ModelToolUseError, model_adapter.ModelTimeoutError,
                           model_adapter.ModelRateLimitError):
            with self.subTest(error_type=error_type.__name__), tempfile.TemporaryDirectory() as directory:
                failed = runner.run(PROTOCOL, Path(directory) / "transport", FailingAdapter(error_type), dry_run=True)
                self.assertEqual(failed["status"], "aborted")
                self.assertEqual(failed["total_model_calls"], 1)
                self.assertEqual(failed["totals"]["exchanges_incomplete"], 1)
                self.assertEqual(failed["totals"]["adapter_errors"], 1)
                self.assertIn(error_type.__name__, failed["error"])

    def test_long_self_refusals_are_invalid_without_retry(self) -> None:
        for message in ("I refuse to answer this question.", "I decline to participate in this simulation.",
                        "I refuse to choose an action."):
            with self.subTest(message=message):
                result = runner.parse_actor_result(actor_result("investigate", message, "synthetic"))
                self.assertTrue(result["invalid"])
                self.assertTrue(result["refusal"])
                self.assertEqual(result["reason"], "self_refusal")


if __name__ == "__main__":
    unittest.main()
