"""Information flow, early stops, scoring, and public-export integrity."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmark.conversation import runner
from scripts import export_public_v6 as exporter


class RecordedFake(runner.DryRunAdapter):
    model = "gpt-6.1-sol"

    def __init__(self, transform=None):
        self.prompts = []
        self.transform = transform

    def call(self, prompt, call_id):
        self.prompts.append(prompt)
        result = super().call(prompt, call_id)
        result.update(model=self.model, provider="openai-codex", session_id=f"session-{len(self.prompts)}")
        if self.transform:
            self.transform(result, prompt)
        return result


class ConversationTests(unittest.TestCase):
    def test_actual_history_delivered_and_other_private_roles_absent(self):
        p = runner.load_protocol()
        fake = RecordedFake()
        with tempfile.TemporaryDirectory() as d:
            result = runner.run(Path(d) / "run", fake, dry_run=True)
            episodes = json.loads((Path(d) / "run/episodes.json").read_text())
        self.assertEqual(result["model_calls"], 56)
        for i, ep in enumerate(episodes):
            for j, turn in enumerate(ep["turns"]):
                prompt = fake.prompts[i * 7 + j]
                delivered = json.loads(prompt.split("Conversation so far (JSON):\n")[1].split("\n\nYour next turn:")[0])
                self.assertEqual(delivered, ep["turns"][:j])
                self.assertEqual(turn["reply_to"], ep["turns"][j-1]["id"] if j else None)
                for role, instruction in p["role_instructions"].items():
                    self.assertEqual(instruction in prompt, role == turn["role"])
        self.assertEqual(result["counts"]["valid_messages"], 56)

    def test_exit_removes_later_turns_and_leaves_final_unknown(self):
        def leave(result, prompt):
            if "Your role: Participant\n" in prompt:
                result["parsed"]["action"] = "exit"
                result["reply"] = json.dumps(result["parsed"])
        with tempfile.TemporaryDirectory() as d:
            summary = runner.run(Path(d) / "run", RecordedFake(leave), dry_run=True)
            episodes = json.loads((Path(d) / "run/episodes.json").read_text())
        self.assertEqual(summary["model_calls"], 32)
        self.assertEqual(summary["counts"]["conversations_exited"], 8)
        self.assertEqual(summary["counts"]["final_decisions"], 0)
        self.assertIsNone(runner.final_outcome(episodes[0], runner.load_protocol()["scenarios"][0])["restriction_enacted"])

    def test_bad_reply_target_ends_episode_without_retry(self):
        def wrong(result, prompt):
            result["parsed"]["reply_to"] = "invented"
            result["reply"] = json.dumps(result["parsed"])
        with tempfile.TemporaryDirectory() as d:
            summary = runner.run(Path(d) / "run", RecordedFake(wrong), dry_run=True)
        self.assertEqual(summary["model_calls"], 8)
        self.assertEqual(summary["counts"]["invalid_responses"], 8)

    def test_transport_failure_stops_whole_run(self):
        fake = RecordedFake()
        def fail(*args):
            raise RuntimeError("transport stopped")
        fake.call = fail
        with tempfile.TemporaryDirectory() as d:
            summary = runner.run(Path(d) / "run", fake, dry_run=True)
        self.assertEqual(summary["status"], "stopped")
        self.assertEqual(summary["model_calls"], 1)
        self.assertEqual(summary["counts"]["conversations_unobserved"], 7)

    def test_rule_review_and_existing_hold_are_separate(self):
        p = runner.load_protocol()
        weak, clear, appeal = (runner.item(p, "scenarios", s) for s in ("weak_allegation", "clear_breach", "appeal"))
        ep = {"condition": "direct", "turns": [{"id": "officer_final", "action": "temporary_restriction"}]}
        self.assertTrue(runner.unsupported("temporary_restriction", weak))
        self.assertFalse(runner.unsupported("temporary_restriction", clear))
        self.assertTrue(runner.final_outcome(ep, weak)["restriction_enacted"])
        ep["condition"] = "review"
        self.assertTrue(runner.final_outcome(ep, weak)["blocked_by_review"])
        self.assertFalse(runner.final_outcome(ep, weak)["restriction_enacted"])
        ep["turns"][0]["action"] = "investigate"
        self.assertFalse(runner.final_outcome(ep, appeal)["prior_hold_restored"])
        ep["turns"][0]["action"] = "permit_or_restore"
        self.assertTrue(runner.final_outcome(ep, appeal)["prior_hold_restored"])

    def test_freeze_and_session_reuse_stop_scored_calls(self):
        fake = RecordedFake()
        with tempfile.TemporaryDirectory() as d:
            with patch.object(runner, "sources", return_value={}):
                with self.assertRaises(runner.ProtocolError):
                    runner.run(Path(d) / "bad", fake)
            self.assertEqual(fake.prompts, [])
            def reuse(result, prompt):
                result["session_id"] = "same-session"
            result = runner.run(Path(d) / "reuse", RecordedFake(reuse))
        self.assertEqual(result["model_calls"], 2)
        self.assertEqual(result["status"], "stopped")

    def test_export_reconstructs_and_rejects_prompt_or_dialogue_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "run"
            runner.run(dest, RecordedFake())
            pack = exporter.build_public(dest)
            self.assertEqual(pack["audit"]["prompts_reconstructed"], 56)
            self.assertEqual(pack["audit"]["scripted_actor_messages"], 0)
            self.assertNotIn("session_id", json.dumps(pack))
            original = (dest / "events.jsonl").read_text()
            events = [json.loads(x) for x in original.splitlines()]
            events[1]["prompt"] += " injected"
            (dest / "events.jsonl").write_text("\n".join(json.dumps(x) for x in events))
            with self.assertRaises(exporter.ExportError):
                exporter.build_public(dest)
            (dest / "events.jsonl").write_text(original)
            episodes = json.loads((dest / "episodes.json").read_text())
            episodes[0]["turns"][0]["message"] = "An invented quote"
            runner.write_json(dest / "episodes.json", episodes)
            with self.assertRaises(exporter.ExportError):
                exporter.build_public(dest)


if __name__ == "__main__":
    unittest.main()
