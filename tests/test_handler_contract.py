"""Handler integration contract without running RunPod, ComfyUI or GPU."""
import ast
import os
import asyncio
import pathlib
import time
import unittest
from unittest.mock import patch

from nl4teens_pipeline import preflight_models, validate_video_outputs

SRC = pathlib.Path(__file__).resolve().parents[1] / "handler.py"


def harness(missing=False):
    source = SRC.read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                and n.name == "handler")
    calls = []
    graph = {
        "105:6": {"class_type": "UNETLoader",
                  "inputs": {"unet_name": "missing.safetensors" if missing else "installed.safetensors"}},
        "126": {"class_type": "VHS_VideoCombine",
                "inputs": {"save_output": True}},
    }
    async def ensure(): calls.append("ensure_comfy")
    async def queue(prompt):
        calls.append("render_started")
        return {"outputs": {}}
    def object_info(cls):
        return {"UNETLoader": {"input": {"required": {
            "unet_name": [["installed.safetensors"]]
        }}}}
    env = {
        "asyncio": asyncio, "Path": pathlib.Path, "time": time,
        "_ensure_comfy": ensure, "_prune_volume_outputs": lambda: None,
        "_load_workflow": lambda path: graph,
        "_patch": lambda prompt, job: prompt,
        "_apply_node_params": lambda prompt, params: prompt,
        "_preflight_object_info": object_info,
        "preflight_models": preflight_models,
        "_queue_and_wait": queue,
        "_collect_outputs": lambda history, prompt, job, inline: ([], {}),
        "_collect_new_files": lambda since, job, inline: [],
        "validate_video_outputs": validate_video_outputs,
    }
    compiled = compile(ast.Module(body=[node], type_ignores=[]), str(SRC), "exec")
    exec(compiled, env)
    return env["handler"], calls


class HandlerContractTests(unittest.TestCase):
    def test_missing_model_aborts_before_render(self):
        handle, calls = harness(missing=True)
        payload = {"id": "offline", "input": {
            "action": "preflight", "workflow": "dummy.json"}}
        with self.assertRaisesRegex(ValueError, "missing.safetensors"):
            asyncio.run(handle(payload))
        self.assertNotIn("render_started", calls)

    def test_preflight_returns_without_render(self):
        handle, calls = harness()
        payload = {"id": "offline", "input": {
            "action": "preflight", "workflow": "dummy.json"}}
        output = asyncio.run(handle(payload))
        self.assertEqual(output["status"], "ok")
        self.assertTrue(output["expects_video"])
        self.assertEqual(output["preflight"]["models_checked"], 1)
        self.assertNotIn("render_started", calls)

    def test_empty_video_result_fails_after_queued_job(self):
        handle, calls = harness()
        payload = {"id": "offline", "input": {
            "workflow": "dummy.json"}}
        with self.assertRaisesRegex(RuntimeError, "Video output missing"):
            asyncio.run(handle(payload))
        self.assertIn("render_started", calls)


    def test_republish_rejects_other_videos(self):
        handle, calls = harness()
        with patch.dict(os.environ, {"NL4TEENS_S3_BUCKET": "nl4teens-video",
                                     "NL4TEENS_FAST_BOOT": "true"}):
            payload = {"id": "offline", "input": {"action": "r2_republish_existing",
                        "source_job_id": "unapproved", "source_filename": "test.mp4"}}
            with self.assertRaisesRegex(ValueError, "unapproved source"):
                asyncio.run(handle(payload))
        self.assertNotIn("render_started", calls)

    def test_verified_fixture_runs_without_render(self):
        handle, calls = harness()
        handle.__globals__["_s3_client"] = lambda cfg: None
        handle.__globals__["republish_existing_video"] = (
            lambda job, client: {"status": "ok", "delivery": "signed_url"})
        with patch.dict(os.environ, {"NL4TEENS_S3_BUCKET": "nl4teens-video",
                                     "NL4TEENS_FAST_BOOT": "true"}):
            payload = {"id": "offline", "input": {"action": "r2_republish_existing",
                "source_job_id": "0f42bcac-49c9-4091-af0b-38f7b1bcad0d-u2",
                "source_filename": "MMH3_T2VA_2026-11-19_00001-audio.mp4"}}
            outcome = asyncio.run(handle(payload))
        self.assertEqual(outcome["delivery"], "signed_url")
        self.assertNotIn("render_started", calls)


if __name__ == "__main__":
    unittest.main()
