"""Offline checks for the v4 scripted-directive and reciprocal AI exchange."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from benchmark import model_adapter
from benchmark.directive import runner


PROTOCOL = Path(__file__).resolve().parents[1] / "benchmark" / "directive" / "protocol_v4.json"


def read_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def actor_result(action: str, message: str, call_id: str, *, provider: str = "openai-codex") -> dict:
    parsed = {"action": action, "message": message}
    return {"reply": json.dumps(parsed), "parsed": parsed, "output_status": "valid_json",
            "call_id": call_id, "model": "gpt-6.1-sol", "provider": provider,
            "session_id": None, "usage": None, "event_count": 0}


class DirectiveTests(unittest.TestCase):
    def test_dry_run_has_twelve_scripted_openings_and_sixty_isolated_model_calls(self) -> None:
        protocol, expected_hash = runner.load_protocol(PROTOCOL)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            summary = runner.run(PROTOCOL, output, runner.DryRunAdapter(), dry_run=True)
            log = read_events(output / "events.jsonl")
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["protocol_sha256"], expected_hash)
        self.assertEqual(summary["total_model_calls"], 60)
        self.assertEqual(summary["total_scripted_stimuli"], 12)
        self.assertEqual(summary["totals"]["episodes_complete"], 12)
        self.assertEqual(summary["totals"]["pressure_delivery_verified"], 4)
        self.assertEqual(summary["totals"]["duty_valid_after_pressure"], 4)
        self.assertEqual(summary["totals"]["duty_unsupported_after_pressure"], 4)
        self.assertEqual(summary["totals"]["senior_reply_unsupported"], 0)
        self.assertEqual(summary["totals"]["duty_reply_unsupported"], 0)
        self.assertEqual(summary["totals"]["enacted_restrictions"], 4)
        self.assertEqual(manifest["episode_order"], protocol["episode_order"])

        episode_starts = [item for item in log if item["kind"] == "episode_start"]
        self.assertEqual(len(episode_starts), 12)
        self.assertEqual([{k: item[k] for k in ("condition", "arm", "scenario")}
                          for item in episode_starts], protocol["episode_order"])
        for item in episode_starts:
            stimulus = item["stimulus"]
            self.assertEqual(stimulus["origin"], "scripted_stimulus")
            self.assertEqual(stimulus["stage"], runner.SCRIPTED_STAGE)
            self.assertEqual(len(stimulus["sha256"]), 64)
        calls = [item for item in log if item["kind"] == "call_start"]
        self.assertEqual(len(calls), 60)
        self.assertEqual(len({item["call_id"] for item in calls}), 60)
        self.assertEqual([item["stage"] for item in calls[:5]], list(runner.STAGES))
        for index, item in enumerate(calls[:5]):
            history = json.loads(item["prompt"].split("Public history (JSON):\n", 1)[1]
                                 .split("\n\nCurrent public event:", 1)[0])
            self.assertEqual(history[0]["origin"], "scripted_stimulus")
            self.assertEqual([turn["stage"] for turn in history[1:]], list(runner.STAGES[:index]))
        for item in calls:
            prompt = item["prompt"]
            self.assertNotIn(item["condition"], prompt)
            for hidden in ("temporary_restriction_supported", "expected_control", "protocol_version"):
                self.assertNotIn(hidden, prompt)
            if item["stage"] == "duty_provisional":
                self.assertTrue(item["stimulus_delivered"])
                self.assertIn('"origin":"scripted_stimulus"', prompt)
            if item["stage"] == "senior_reply":
                self.assertNotIn(protocol["role_instructions"]["duty"], prompt)
                self.assertNotIn(protocol["role_instructions"]["participant"], prompt)
            elif item["stage"].startswith("duty"):
                self.assertNotIn(protocol["role_instructions"]["senior"], prompt)
                self.assertNotIn(protocol["role_instructions"]["participant"], prompt)
        self.assertNotIn("Senior advice as a recommendation, not as a rule change",
                         protocol["role_instructions"]["duty"])
        weak_starts = [item for item in episode_starts if item["scenario"] == "weak_allegation"]
        for condition in runner.CONDITION_IDS:
            matched = [item for item in weak_starts if item["condition"] == condition]
            self.assertEqual(len(matched), 2)
            self.assertEqual(matched[0]["event"], matched[1]["event"])

    def test_missing_or_changed_scripted_directive_aborts_before_first_call(self) -> None:
        original = runner.build_prompt

        def omit_history(*args):
            prompt = original(*args)
            if args[3] == "duty_provisional":
                start = prompt.index("Public history (JSON):\n")
                end = prompt.index("\n\nCurrent public event:", start)
                return prompt[:start] + "Public history (JSON):\n[]" + prompt[end:]
            return prompt

        class CountingAdapter:
            model = "dry-run"

            def __init__(self) -> None:
                self.calls = 0

            def call(self, prompt: str, call_id: str) -> dict:
                self.calls += 1
                return runner.DryRunAdapter().call(prompt, call_id)

        adapter = CountingAdapter()
        with tempfile.TemporaryDirectory() as directory, patch.object(runner, "build_prompt", side_effect=omit_history):
            output = Path(directory) / "run"
            summary = runner.run(PROTOCOL, output, adapter, dry_run=True)
            log = read_events(output / "events.jsonl")
        self.assertEqual(summary["status"], "aborted")
        self.assertEqual(summary["total_model_calls"], 0)
        self.assertEqual(adapter.calls, 0)
        self.assertIn("exact scripted directive was not delivered", summary["error"])
        ended = next(item for item in log if item["kind"] == "episode_end")
        self.assertEqual(set(ended["stage_scores"]), {runner.SCRIPTED_STAGE})

    def test_aborted_run_counts_only_emitted_scripted_openings(self) -> None:
        class FailFirst:
            model = "dry-run"

            def call(self, prompt: str, call_id: str) -> dict:
                raise model_adapter.ModelToolUseError(call_id, "synthetic tool event")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            summary = runner.run(PROTOCOL, output, FailFirst(), dry_run=True)
            log = read_events(output / "events.jsonl")
        self.assertEqual(summary["status"], "aborted")
        self.assertEqual(summary["total_model_calls"], 1)
        self.assertEqual(summary["total_episodes_scheduled"], 12)
        self.assertEqual(summary["total_scripted_stimuli"], 1)
        self.assertEqual(sum(item["kind"] == "episode_start" for item in log), 1)

    def test_scored_source_hash_gate_fails_before_output_or_model_call(self) -> None:
        class CountingAdapter:
            model = "gpt-6.1-sol"

            def __init__(self) -> None:
                self.calls = 0

            def call(self, prompt: str, call_id: str) -> dict:
                self.calls += 1
                return actor_result("investigate", "Synthetic response.", call_id)

        adapter = CountingAdapter()
        original = runner.SOURCE_HASHES_PATH.read_text(encoding="utf-8")
        runner_hash = runner.sha256(Path(runner.__file__))
        self.assertIn(runner_hash, original)
        with tempfile.TemporaryDirectory() as directory:
            bad_pin = Path(directory) / "bad-hashes.md"
            bad_pin.write_text(original.replace(runner_hash, "0" * 64, 1), encoding="utf-8")
            output = Path(directory) / "run"
            with patch.object(runner, "SOURCE_HASHES_PATH", bad_pin):
                with self.assertRaisesRegex(runner.ProtocolError, "source hash differs"):
                    runner.run(PROTOCOL, output, adapter, dry_run=False)
            self.assertFalse(output.exists())
        self.assertEqual(adapter.calls, 0)

    def test_scored_output_requires_explicit_path_outside_public_repo(self) -> None:
        class NeverCalled:
            model = "gpt-6.1-sol"

            def __init__(self) -> None:
                self.calls = 0

            def call(self, prompt: str, call_id: str) -> dict:
                self.calls += 1
                raise AssertionError("model call should be blocked")

        adapter = NeverCalled()
        inside = runner.ROOT / "benchmark" / "directive" / "runs" / f"forbidden-{uuid.uuid4().hex}"
        with self.assertRaisesRegex(runner.ProtocolError, "outside the public repository"):
            runner.run(PROTOCOL, inside, adapter, dry_run=False)
        self.assertFalse(inside.exists())
        self.assertEqual(adapter.calls, 0)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(runner.main([]), 2)

    def test_dry_run_cli_default_uses_system_temp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            captured = io.StringIO()
            with patch.object(runner.tempfile, "gettempdir", return_value=directory), redirect_stdout(captured):
                self.assertEqual(runner.main(["--dry-run"]), 0)
            result = json.loads(captured.getvalue())
            output = Path(result["output_dir"])
            self.assertEqual(output.parent.resolve(), Path(directory).resolve())
            self.assertTrue((output / "summary.json").is_file())

    def test_synthetic_transport_uses_scored_route_checks_without_model_calls(self) -> None:
        class RoutedFake:
            model = "gpt-6.1-sol"

            def __init__(self) -> None:
                self.fake = runner.DryRunAdapter()
                self.calls = 0

            def call(self, prompt: str, call_id: str) -> dict:
                self.calls += 1
                result = self.fake.call(prompt, call_id)
                result["model"] = self.model
                result["provider"] = "openai-codex"
                return result

        adapter = RoutedFake()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "synthetic-scored-path"
            summary = runner.run(PROTOCOL, output, adapter, dry_run=False)
            log = read_events(output / "events.jsonl")
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["total_model_calls"], 60)
        self.assertEqual(adapter.calls, 60)
        self.assertEqual(sum(not item["route_request_consistent"] for item in log
                             if item["kind"] == "call_result"), 0)

    def test_reviewer_blocks_unsupported_final_but_passes_supported_control(self) -> None:
        protocol, _ = runner.load_protocol(PROTOCOL)
        weak = next(s for s in protocol["scenarios"] if s["id"] == "weak_allegation")
        clear = next(s for s in protocol["scenarios"] if s["id"] == "clear_breach")
        review = next(c for c in protocol["conditions"] if c["id"] == "neutral_review")
        direct = next(c for c in protocol["conditions"] if c["id"] == "neutral_unilateral")
        for condition, scenario, arm, bad in ((review, weak, "pressure", True),
                                               (direct, weak, "pressure", True),
                                               (review, clear, "control", False)):
            with self.subTest(condition=condition["id"], arm=arm):
                stimulus = runner.render_directive(protocol, arm, condition)
                history = [{k: v for k, v in stimulus.items() if k != "sha256"}]
                history.extend({"stage": stage, "action": "temporary_restriction"}
                               for stage in runner.STAGES if stage != "participant_response")
                history.insert(4, {"stage": "participant_response", "action": "appeal"})
                score = runner.counters()
                outcome = runner.final_outcome(score, condition, scenario, arm,
                                               arm == "pressure", history)
                self.assertEqual(outcome["stimulus_origin"], "scripted_stimulus")
                self.assertEqual(outcome["stimulus_unsupported"], bad)
                self.assertEqual(outcome["final_unsupported"], bad)
                blocked = condition["governance"] == "review" and bad
                self.assertEqual(outcome["review_blocked"], blocked)
                self.assertEqual(outcome["enacted_restriction"], not blocked)
                self.assertEqual(score["review_blocks"], int(blocked))

    def test_participant_exit_keeps_scripted_and_observed_stage_scores(self) -> None:
        class ExitFirst:
            def __init__(self) -> None:
                self.fake = runner.DryRunAdapter()
                self.calls = 0

            def call(self, prompt: str, call_id: str) -> dict:
                self.calls += 1
                if self.calls == 4:
                    return actor_result("exit", "I exit now.", call_id)
                return self.fake.call(prompt, call_id)

        adapter = ExitFirst()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            summary = runner.run(PROTOCOL, output, adapter, dry_run=True)
            log = read_events(output / "events.jsonl")
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["total_model_calls"], 59)
        first_end = next(item for item in log if item["kind"] == "episode_end")
        self.assertEqual(first_end["reason"], "participant_exit")
        self.assertEqual(first_end["calls_observed"], 4)
        self.assertEqual(set(first_end["stage_scores"]),
                         {"senior_directive", "duty_provisional", "senior_reply", "duty_reply"})
        self.assertEqual(first_end["stage_scores"]["senior_directive"]["origin"], "scripted_stimulus")
        self.assertEqual(first_end["stage_scores"]["senior_reply"]["origin"], "model_call")
        self.assertEqual(summary["totals"]["episodes_incomplete"], 1)

    def test_tool_failure_and_route_drift_abort_without_retry(self) -> None:
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

        for adapter, count in ((ToolFailure(), 1), (Drift(), 2)):
            with self.subTest(adapter=type(adapter).__name__), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "run"
                summary = runner.run(PROTOCOL, output, adapter, dry_run=False)
                log = read_events(output / "events.jsonl")
                self.assertEqual(summary["status"], "aborted")
                self.assertEqual(summary["total_model_calls"], count)
                self.assertEqual(adapter.calls, count)
                self.assertEqual(log[-1]["kind"], "run_abort")
                self.assertEqual(summary["totals"]["episodes_incomplete"], 1)
                if isinstance(adapter, Drift):
                    replies = [item for item in log if item["kind"] == "call_result"]
                    self.assertTrue(replies[0]["route_request_consistent"])
                    self.assertFalse(replies[1]["route_request_consistent"])
                    ended = next(item for item in log if item["kind"] == "episode_end")
                    self.assertEqual(set(ended["stage_scores"]),
                                     {"senior_directive", "duty_provisional"})

    def test_protocol_rejects_duplicate_schedule_and_changed_pressure_action(self) -> None:
        source = json.loads(PROTOCOL.read_text(encoding="utf-8"))
        for mutation in ("schedule", "directive"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                protocol = json.loads(json.dumps(source))
                if mutation == "schedule":
                    protocol["episode_order"][0] = protocol["episode_order"][1]
                else:
                    protocol["scripted_directives"]["pressure"]["action"] = "investigate"
                path = Path(directory) / "changed.json"
                path.write_text(json.dumps(protocol), encoding="utf-8")
                with self.assertRaises(runner.ProtocolError):
                    runner.load_protocol(path)


if __name__ == "__main__":
    unittest.main()
