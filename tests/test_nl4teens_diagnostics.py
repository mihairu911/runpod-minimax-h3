"""Portable no-GPU validation of persisted diagnostic events."""
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import nl4teens_diagnostics as diag


class PersistentDiagnosticsTests(unittest.TestCase):
    def test_events_persist_without_prompts_or_secrets(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"NL4TEENS_DIAG_ROOT": td}):
                ok = diag.log_event("../job?a", "heartbeat", elapsed_seconds=32,
                                    running=1, pending=0, vram_free_mib=4096,
                                    prompt="sensitive text", accessSecret="private-token",
                                    signed_url="https://example/?secret=sensitive",
                                    error_type="TimeoutError")
            self.assertTrue(ok)
            path = pathlib.Path(td) / "jobs" / ".._job_a" / "events.jsonl"
            event = json.loads(path.read_text())
            self.assertEqual(event["stage"], "heartbeat")
            self.assertEqual(event["running"], 1)
            self.assertEqual(event["vram_free_mib"], 4096)
            self.assertNotIn("prompt", event)
            self.assertNotIn("accessSecret", event)
            self.assertNotIn("signed_url", event)

    def test_worker_log_is_unique_and_on_volume(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"NL4TEENS_DIAG_ROOT": td, "HOSTNAME": "../node.example"}):
                log = diag.worker_comfy_log_path()
            self.assertEqual(log.parent, pathlib.Path(td) / "workers")
            self.assertFalse("/../" in str(log))
            self.assertTrue(log.suffix == ".log")

    def test_queue_snapshot_never_serializes_prompt_contents(self):
        def api(path):
            if path == "/queue":
                return {"queue_running": [[1, "prompt-id", {"prompt": "private conversation"}]],
                        "queue_pending": [[2, "q", {"prompt": "secret"}]]}
            return {"devices": [{"vram_free": 1048576000, "vram_total": 2097152000}]}
        snap = diag.queue_snapshot(api)
        self.assertEqual(snap, {"running": 1, "pending": 1,
                                "vram_free_mib": 1000.0, "total_vram_mib": 2000.0})
        self.assertNotIn("private", json.dumps(snap))

    def test_queue_snapshot_survives_status_api_error(self):
        snap = diag.queue_snapshot(lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
        self.assertEqual(snap, {"running": -1, "pending": -1})

    def test_event_bad_fields_do_not_break_recording(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"NL4TEENS_DIAG_ROOT": td}):
                self.assertTrue(diag.log_event("safe", "queued", workflow="test.json",
                    seconds=None, log_path="/runpod-volume/private/key-123/comfy.log"))
                log = pathlib.Path(td)/"jobs"/"safe"/"events.jsonl"
                raw = log.read_text()
                self.assertIn("comfy.log",raw)
                self.assertNotIn("key-123",raw)


if __name__ == "__main__":
    unittest.main()
