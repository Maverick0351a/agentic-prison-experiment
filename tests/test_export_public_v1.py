"""Checks for the versioned, public-only replay export."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import export_public_v1 as exporter  # noqa: E402


class PublicExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pack = json.loads((ROOT / "docs" / "data" / "v1-public.json").read_text(encoding="utf-8"))

    def test_public_pack_is_complete_and_browser_copy_matches(self) -> None:
        pack = self.pack
        self.assertEqual(set(pack), {
            "schema_version", "title", "model", "protocol_sha256", "conditions",
            "blocks", "scenarios", "episodes", "summary", "limitations",
        })
        self.assertEqual(len(pack["conditions"]), 4)
        self.assertEqual(len(pack["episodes"]), 8)
        self.assertEqual(sum(len(ep["decisions"]) for ep in pack["episodes"]), 32)
        self.assertEqual(pack["summary"]["total_model_calls"], 64)
        self.assertEqual(pack["summary"]["total_authority_decisions"], 32)
        for counts in pack["summary"]["by_condition"].values():
            self.assertEqual(counts["enacted_unsupported_restrictions"], 0)
            self.assertEqual(counts["appeals_requested"], 2)
            self.assertEqual(counts["appeals_referred"], 0)
            self.assertEqual(counts["corrections"], 2)
        js = (ROOT / "docs" / "data.js").read_text(encoding="utf-8")
        prefix = "window.AUTHORITY_LAB_DATA = "
        self.assertTrue(js.startswith(prefix) and js.endswith(";\n"))
        self.assertEqual(json.loads(js[len(prefix):-2]), pack)

    def test_whitelist_excludes_private_metadata(self) -> None:
        serialized = json.dumps(self.pack, ensure_ascii=False)
        self.assertIsNone(exporter.SENSITIVE.search(serialized))
        for key in ("session_id", "call_id", "prompt", "usage", "created_utc", "protocol_path"):
            self.assertNotIn(f'"{key}"', serialized)
        for episode in self.pack["episodes"]:
            self.assertEqual(set(episode), {"block", "condition", "decisions"})
            for decision in episode["decisions"]:
                self.assertEqual(set(decision), set(exporter.DECISION_KEYS))

    def _make_source(self, root: Path) -> tuple[Path, Path]:
        source = root / "source"
        source.mkdir()
        scenarios = [
            {"id": row["id"], "title": row["title"], "event": row["event_template"]}
            for row in self.pack["scenarios"]
        ]
        protocol = root / "scenarios.json"
        protocol.write_text(json.dumps({"blocks": self.pack["blocks"], "scenarios": scenarios}), encoding="utf-8")
        digest = hashlib.sha256(protocol.read_bytes()).hexdigest()
        (source / "manifest.json").write_text(json.dumps({
            "max_model_calls": 64, "protocol_sha256": digest, "model": self.pack["model"]
        }), encoding="utf-8")
        (source / "summary.json").write_text(json.dumps({
            "status": "completed", "mode": "scored", "total_model_calls": 64,
            "model": self.pack["model"], "protocol_sha256": digest,
            "conditions": self.pack["summary"]["by_condition"],
        }), encoding="utf-8")
        rows = []
        call_number = 0
        for episode in self.pack["episodes"]:
            block, condition = episode["block"], episode["condition"]
            rows.append({"kind": "episode_start", "block": block, "condition": condition})
            for round_index, decision in enumerate(episode["decisions"]):
                for _ in range(2):
                    call_number += 1
                    call_id = f"call-{call_number:02d}"
                    rows.append({"kind": "call_start", "call_id": call_id})
                    rows.append({"kind": "call_result", "call_id": call_id, "model": self.pack["model"],
                                 "provider": "fixture", "output_status": "valid_json", "invalid": False, "refusal": False})
                rows.append({"kind": "decision", "block": block, "condition": condition,
                             "round": round_index, "valid_authority_decision": True, **decision})
            rows.append({"kind": "episode_end", "block": block, "condition": condition,
                         "status": "completed", "rounds_completed": 4})
        (source / "events.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        return source, protocol

    def test_export_validates_source_and_rejects_sensitive_text(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source, protocol = self._make_source(Path(folder))
            rebuilt = exporter.build_pack(source, protocol)
            self.assertEqual(rebuilt["episodes"], self.pack["episodes"])
            rows = [json.loads(line) for line in (source / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            decision = next(row for row in rows if row["kind"] == "decision")
            decision["authority_message"] = r"See C:\Users\Example\secret.txt"
            (source / "events.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(exporter.ExportError, "Sensitive-looking"):
                exporter.build_pack(source, protocol)

    def test_partial_run_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source, protocol = self._make_source(Path(folder))
            summary_path = source / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["status"] = "aborted"
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaisesRegex(exporter.ExportError, "completed scored run"):
                exporter.build_pack(source, protocol)


if __name__ == "__main__":
    unittest.main()
