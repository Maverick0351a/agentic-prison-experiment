"""Offline checks for the published authority benchmark."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from benchmark import model_adapter, pilot


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmark" / "scenarios.json"


def events_at(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class BenchmarkTests(unittest.TestCase):
    def test_frozen_dry_run_completes_all_episodes_with_isolated_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            summary = pilot.run(PROTOCOL, run_dir, pilot.DryRunAdapter(), dry_run=True)
            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["total_model_calls"], 64)
            self.assertEqual(set(summary["conditions"]), set(pilot.CONDITION_BY_ID))
            for counts in summary["conditions"].values():
                self.assertEqual(counts["episodes"], 2)
                self.assertEqual(counts["valid_authority_decisions"], 8)
                self.assertEqual(counts["proposed_unsupported_restrictions"], 0)
                self.assertEqual(counts["enacted_restrictions"], 2)
                self.assertEqual(counts["appeals_resolved"], 2)

            records = events_at(run_dir / "events.jsonl")
            starts = [record for record in records if record["kind"] == "call_start"]
            results = [record for record in records if record["kind"] == "call_result"]
            self.assertEqual(len(starts), 64)
            self.assertEqual(len(results), 64)
            self.assertEqual(len({record["call_id"] for record in starts}), 64)
            for record in starts:
                prompt = record["prompt"]
                self.assertNotIn("temporary_restriction_supported", prompt)
                self.assertNotIn("appeal_case", prompt)
                self.assertNotIn("expected_control", prompt)
                self.assertNotIn("Stanford Prison Experiment", prompt)
                self.assertNotIn(record["condition"], prompt)
                if record["actor"] == "participant":
                    self.assertNotIn("Apply the written rules fairly.", prompt)
                else:
                    self.assertNotIn("Choose one action in your own interest", prompt)

            self.assertEqual(json.loads((run_dir / "summary.json").read_text(encoding="utf-8")), summary)
            self.assertTrue((run_dir / "manifest.json").is_file())
            self.assertTrue((run_dir / "REPORT.md").is_file())

    def test_invalid_actor_reply_ends_only_its_episode_without_retry(self) -> None:
        class InvalidFirstAdapter:
            def __init__(self) -> None:
                self.calls = 0
                self.fake = pilot.DryRunAdapter()

            def call(self, prompt: str, call_id: str) -> dict:
                self.calls += 1
                if self.calls == 1:
                    return {"reply": "not JSON", "parsed": None, "output_status": "invalid_json"}
                return self.fake.call(prompt, call_id)

        adapter = InvalidFirstAdapter()
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            summary = pilot.run(PROTOCOL, run_dir, adapter, dry_run=False)
            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["total_model_calls"], 57)
            self.assertEqual(adapter.calls, 57)
            self.assertEqual(summary["conditions"]["neutral_unilateral"]["episodes_incomplete"], 1)
            self.assertEqual(sum(x["episodes_incomplete"] for x in summary["conditions"].values()), 1)
            self.assertEqual(sum(x["invalid_outputs"] for x in summary["conditions"].values()), 1)
            records = events_at(run_dir / "events.jsonl")
            self.assertEqual(len([r for r in records if r["kind"] == "episode_incomplete"]), 1)
            self.assertEqual(len([r for r in records if r["kind"] == "call_start"]), 57)

    def test_protocol_rejects_removed_positive_control(self) -> None:
        protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
        protocol["scenarios"][0]["temporary_restriction_supported"] = False
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / "scenarios.json"
            changed.write_text(json.dumps(protocol), encoding="utf-8")
            with self.assertRaises(pilot.ProtocolError):
                pilot.load_protocol(changed)

    def test_hermes_route_arguments_are_bounded_and_tool_restricted(self) -> None:
        adapter = model_adapter.HermesCodexAdapter(hermes_executable="hermes", timeout_seconds=90)
        command = adapter.build_command(Path("empty"))
        self.assertEqual(command[:2], ["hermes", "chat"])
        self.assertIn("--oneshot", command)
        self.assertIn("--safe-mode", command)
        self.assertEqual(command[command.index("--provider") + 1], "openai-codex")
        self.assertEqual(command[command.index("--toolsets") + 1], "clarify")
        self.assertEqual(command[command.index("--max-turns") + 1], "1")
        self.assertEqual(command[command.index("--run-budget") + 1], "60")


if __name__ == "__main__":
    unittest.main()
