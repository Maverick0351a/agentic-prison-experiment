"""Focused offline checks for the v3 conflicting-authority protocol."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from benchmark import model_adapter
from benchmark.conflict import runner


PROTOCOL = Path(__file__).resolve().parents[1] / "benchmark" / "conflict" / "protocol_v3.json"


def events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def response(action: str, message: str, call_id: str, *, provider: str = "openai-codex") -> dict:
    parsed = {"action": action, "message": message}
    return {"reply": json.dumps(parsed), "parsed": parsed, "output_status": "valid_json",
            "call_id": call_id, "model": "gpt-6.1-sol", "provider": provider,
            "session_id": None, "usage": None, "event_count": 0}


class ConflictTests(unittest.TestCase):
    def test_frozen_schedule_role_isolation_and_manipulation_denominator(self) -> None:
        protocol, expected_hash = runner.load_protocol(PROTOCOL)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            summary = runner.run(PROTOCOL, output, runner.DryRunAdapter(), dry_run=True)
            log = events(output / "events.jsonl")
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["total_model_calls"], 60)
        self.assertEqual(summary["total_episodes_scheduled"], 12)
        self.assertEqual(summary["protocol_sha256"], expected_hash)
        self.assertEqual(summary["totals"]["manipulation_opportunities"], 4)
        self.assertEqual(summary["totals"]["manipulation_structured_success"], 4)
        self.assertEqual(summary["totals"]["duty_exposure_opportunities"], 4)
        self.assertEqual(summary["totals"]["duty_no_restriction_after_exposure"], 4)
        self.assertEqual(summary["totals"]["senior_unsupported_to_supported"], 4)
        self.assertEqual(summary["totals"]["enacted_restrictions"], 4)
        self.assertEqual(len(summary["episodes"]), 12)

        starts = [item for item in log if item["kind"] == "episode_start"]
        self.assertEqual([{k: item[k] for k in ("condition", "arm", "scenario")}
                          for item in starts], protocol["episode_order"])
        calls = [item for item in log if item["kind"] == "call_start"]
        self.assertEqual(len(calls), 60)
        self.assertEqual(len({item["call_id"] for item in calls}), 60)
        self.assertEqual([item["stage"] for item in calls[:5]], list(runner.STAGES))
        for index, item in enumerate(calls[:5]):
            history = json.loads(item["prompt"].split("Public history (JSON):\n", 1)[1]
                                 .split("\n\nCurrent public event:", 1)[0])
            self.assertEqual([turn["stage"] for turn in history], list(runner.STAGES[:index]))
        for item in calls:
            prompt = item["prompt"]
            self.assertNotIn(item["condition"], prompt)
            for hidden in ("temporary_restriction_supported", "expected_control", "protocol_version"):
                self.assertNotIn(hidden, prompt)
            if item["stage"] in ("senior_initial", "senior_reply"):
                self.assertIn(protocol["arm_instructions"][item["arm"]], prompt)
                self.assertNotIn(protocol["role_instructions"]["duty"], prompt)
                self.assertNotIn(protocol["role_instructions"]["participant"], prompt)
            else:
                self.assertNotIn(protocol["arm_instructions"]["baseline"], prompt)
                self.assertNotIn(protocol["arm_instructions"]["advocacy"], prompt)
                self.assertNotIn(protocol["role_instructions"]["senior"], prompt)
        weak = next(s for s in protocol["scenarios"] if s["id"] == "weak_allegation")
        clear = next(s for s in protocol["scenarios"] if s["id"] == "clear_breach")
        for shared in ("posted and acknowledged schedule closes it at 18:00", "No conflicting notice exists"):
            self.assertIn(shared, weak["event"])
            self.assertIn(shared, clear["event"])

    def test_fixed_reviewer_blocks_unsupported_final_after_recording_proposal(self) -> None:
        protocol, _ = runner.load_protocol(PROTOCOL)
        weak = next(s for s in protocol["scenarios"] if s["id"] == "weak_allegation")
        history = [
            {"stage": "senior_initial", "action": "temporary_restriction"},
            {"stage": "duty_provisional", "action": "temporary_restriction"},
            {"stage": "senior_reply", "action": "temporary_restriction"},
            {"stage": "participant_response", "action": "appeal"},
            {"stage": "duty_final", "action": "temporary_restriction"},
        ]
        for governance, blocked in (("review", True), ("unilateral", False)):
            with self.subTest(governance=governance):
                condition = next(c for c in protocol["conditions"] if c["governance"] == governance)
                score = runner.counters()
                outcome = runner.final_outcome(score, condition, weak, history)
                self.assertTrue(outcome["senior_initial_unsupported"])
                self.assertTrue(outcome["duty_provisional_unsupported"])
                self.assertTrue(outcome["final_unsupported"])
                self.assertEqual(outcome["review_blocked"], blocked)
                self.assertEqual(outcome["enacted_restriction"], not blocked)
                self.assertEqual(score["review_blocks"], int(blocked))
                self.assertEqual(score["enacted_unsupported_restrictions"], int(not blocked))

    def test_participant_exit_keeps_observed_scores_and_skips_final_call(self) -> None:
        class ExitFirst:
            def __init__(self) -> None:
                self.fake = runner.DryRunAdapter()
                self.calls = 0

            def call(self, prompt: str, call_id: str) -> dict:
                self.calls += 1
                if self.calls == 4:
                    return response("exit", "I exit this exchange now.", call_id)
                return self.fake.call(prompt, call_id)

        adapter = ExitFirst()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            summary = runner.run(PROTOCOL, output, adapter, dry_run=True)
            log = events(output / "events.jsonl")
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["total_model_calls"], 59)
        self.assertEqual(adapter.calls, 59)
        first_end = next(item for item in log if item["kind"] == "episode_end")
        self.assertEqual(first_end["status"], "incomplete")
        self.assertEqual(first_end["reason"], "participant_exit")
        self.assertEqual(first_end["calls_observed"], 4)
        self.assertEqual(set(first_end["stage_scores"]),
                         {"senior_initial", "duty_provisional", "senior_reply"})
        self.assertTrue(all("unsupported" in value for value in first_end["stage_scores"].values()))
        first_identity = {k: first_end[k] for k in ("condition", "arm", "scenario")}
        self.assertFalse(any(item["kind"] == "episode_outcome" and
                             all(item.get(k) == v for k, v in first_identity.items()) for item in log))

    def test_tool_failure_and_provider_drift_stop_without_retries(self) -> None:
        class ToolFailure:
            model = "gpt-6.1-sol"

            def __init__(self) -> None:
                self.calls = 0

            def call(self, prompt: str, call_id: str) -> dict:
                self.calls += 1
                raise model_adapter.ModelToolUseError(call_id, "synthetic tool event")

        class Drift:
            model = "gpt-6.1-sol"

            def __init__(self) -> None:
                self.calls = 0
                self.fake = runner.DryRunAdapter()

            def call(self, prompt: str, call_id: str) -> dict:
                self.calls += 1
                result = self.fake.call(prompt, call_id)
                result["model"] = self.model
                result["provider"] = "other-provider" if self.calls == 2 else "openai-codex"
                return result

        for adapter, expected_calls in ((ToolFailure(), 1), (Drift(), 2)):
            with self.subTest(adapter=type(adapter).__name__), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "run"
                summary = runner.run(PROTOCOL, output, adapter, dry_run=False)
                log = events(output / "events.jsonl")
                self.assertEqual(summary["status"], "aborted")
                self.assertEqual(summary["total_model_calls"], expected_calls)
                self.assertEqual(adapter.calls, expected_calls)
                self.assertEqual(log[-1]["kind"], "run_abort")
                self.assertEqual(sum(cell["episodes_incomplete"] for cell in summary["cells"].values()), 1)
                if isinstance(adapter, Drift):
                    replies = [item for item in log if item["kind"] == "call_result"]
                    self.assertTrue(replies[0]["route_verified"])
                    self.assertFalse(replies[1]["route_verified"])
                    ended = next(item for item in log if item["kind"] == "episode_end")
                    self.assertEqual(set(ended["stage_scores"]), {"senior_initial"})

    def test_schedule_rejects_duplicate_or_advocacy_control(self) -> None:
        source = json.loads(PROTOCOL.read_text(encoding="utf-8"))
        for mutation in ("duplicate", "advocacy_control"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                protocol = json.loads(json.dumps(source))
                if mutation == "duplicate":
                    protocol["episode_order"][0] = protocol["episode_order"][1]
                else:
                    control = next(e for e in protocol["episode_order"] if e["scenario"] == "clear_breach")
                    control["arm"] = "advocacy"
                path = Path(directory) / "changed.json"
                path.write_text(json.dumps(protocol), encoding="utf-8")
                with self.assertRaises(runner.ProtocolError):
                    runner.load_protocol(path)


if __name__ == "__main__":
    unittest.main()
