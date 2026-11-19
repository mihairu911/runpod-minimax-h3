"""N&L 4teens pipeline tests: preflight, output correctness, signed links and QC."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nl4teens_pipeline as p


class ModelPreflightTests(unittest.TestCase):
    def _provider(self, cls):
        return {cls: {"input": {"required": {
            "unet_name": [["installed_int8.safetensors", "backup.safetensors"]],
            "vae_name": [["vae.safetensors"]],
        }}}}

    def test_installed_model_passes(self):
        graph = {"105:6": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "installed_int8.safetensors"}}}
        result = p.preflight_models(graph, self._provider)
        self.assertEqual(result["models_checked"], 1)

    def test_missing_model_fails_before_gpu(self):
        graph = {"105:6": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "Minimax-H3-Hybrid-DMAD-PDMD_int8.safetensors"}}}
        with self.assertRaisesRegex(ValueError, "installed_int8.safetensors"):
            p.preflight_models(graph, self._provider)

    def test_invalid_comfyui_metadata_fails_closed(self):
        graph = {"7": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "installed_int8.safetensors"}}}
        with self.assertRaisesRegex(RuntimeError, "missing ComfyUI object info"):
            p.preflight_models(graph, lambda cls: {})

    def test_unrelated_node_not_a_model(self):
        graph = {"10": {"class_type": "ComfyUI-PerfectVideoResolution", "inputs": {
            "model": "MiniMax H3"}}}
        result = p.preflight_models(graph, lambda cls: self.fail("should not query"))
        self.assertEqual(result["models_checked"], 0)


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.graph = {"126": {"class_type": "VHS_VideoCombine",
                              "inputs": {"save_output": True}}}

    def test_empty_output_is_error(self):
        with self.assertRaisesRegex(RuntimeError, "Video output missing"):
            p.validate_video_outputs(self.graph, [])

    def test_text_only_graph_can_return_no_video(self):
        graph = {"1": {"class_type": "ShowText", "inputs": {"text": "ok"}}}
        self.assertEqual(p.validate_video_outputs(graph, [])["video_outputs"], 0)

    def test_saved_mp4_passes(self):
        video = {"filename": "clip.mp4", "saved": True,
                 "volume_path": "/runpod-volume/test/clip.mp4"}
        self.assertEqual(p.validate_video_outputs(self.graph, [video])["video_outputs"], 1)

    def test_unsaved_mp4_is_error(self):
        with self.assertRaisesRegex(RuntimeError, "not persisted"):
            p.validate_video_outputs(self.graph, [{"filename": "clip.mp4", "b64": "xyz"}])

    def test_disabled_video_saver_requires_nothing(self):
        graph = {"126": {"class_type": "VHS_VideoCombine",
                         "inputs": {"save_output": False}}}
        self.assertFalse(p.expects_video(graph))


class QCTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / "clip.mp4"
        self.file.write_bytes(b"x" * 100)

    def test_ffprobe_streams_and_duration(self):
        probe = {"streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 576,
             "height": 1024, "avg_frame_rate": "24/1"},
            {"codec_type": "audio", "codec_name": "aac",
             "channels": 2, "sample_rate": "32000"}],
            "format": {"duration": "5.167", "size": "100"}}
        with patch.object(p.subprocess, "run",
                          return_value=SimpleNamespace(stdout=json.dumps(probe))):
            qc = p.inspect_video(self.file, expected_seconds=5, require_audio=True)
        self.assertEqual(qc["status"], "ok")
        self.assertTrue(qc["audio_present"])
        self.assertEqual(qc["duration_seconds"], 5.167)
        self.assertEqual(qc["fps"], 24)
        self.assertEqual(qc["duration_delta_seconds"], 0.167)

    def test_corrupt_video_fails(self):
        probe = {"streams": [], "format": {"duration": "5"}}
        with patch.object(p.subprocess, "run",
                          return_value=SimpleNamespace(stdout=json.dumps(probe))):
            with self.assertRaisesRegex(RuntimeError, "no valid video stream"):
                p.inspect_video(self.file)


class DeliveryTests(unittest.TestCase):
    def test_no_config_no_external_link(self):
        self.assertIsNone(p.optional_delivery_cfg({"input": {}}, {}))
        self.assertEqual(p.signed_media_upload(b"xyz", "test.mp4", {"id":"job"}, None, None),
                         {"delivery": "volume_only"})

    def test_signed_url_generated_from_secret_config(self):
        calls = []
        class FakeClient:
            def put_object(self, **kw):
                calls.append(("put", kw))
            def generate_presigned_url(self, op, Params, ExpiresIn):
                calls.append(("sign", (op, Params, ExpiresIn)))
                return "https://example.test/signed?sig=sample"
        config = {"bucketName": "private-bucket", "endpointUrl": "https://r2.example",
                  "accessId": "access", "accessSecret": "secret"}
        out = p.signed_media_upload(b"abc", "sample.mp4", {"id": "123/456"},
                                    config, lambda cfg: FakeClient(), ttl=120)
        self.assertEqual(out["delivery"], "signed_url")
        self.assertIn("/signed?", out["url"])
        self.assertEqual(calls[0][1]["Key"], "nl4teens/artifacts/123_456/sample.mp4")
        self.assertEqual(calls[1][1][2], 120)
        self.assertNotIn("secret", json.dumps(out))


class RepublishTests(unittest.TestCase):
    def test_existing_mp4_delivered_and_checked_without_render(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            saved = root / "prior_job" / "old.mp4"
            saved.parent.mkdir()
            saved.write_bytes(b"known-video-test-bytes-" * 10)
            class Client:
                def put_object(self, **args):
                    self.key = args["Key"]
                def generate_presigned_url(self, op, Params, ExpiresIn):
                    return "https://storage.example/signed-test"
            job = {"id": "republish_job", "input": {
                "action": "r2_republish_existing", "source_job_id": "prior_job",
                "source_filename": "old.mp4", "require_audio": True,
                "s3Config": {"endpointUrl": "https://a.r2.cloudflarestorage.com",
                             "accessId": "test", "accessSecret": "test",
                             "bucketName": "nl4teens-video"}}}
            with patch.object(p, "inspect_video", return_value={
                    "status": "ok", "duration_seconds": 5.167,
                    "audio_present": True}):
                result = p.republish_existing_video(job, lambda cfg: Client(), root=root)
            self.assertEqual(result["delivery"], "signed_url")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["bytes"], saved.stat().st_size)
            self.assertTrue(result["qc"]["audio_present"])
            self.assertEqual(saved.read_bytes(), b"known-video-test-bytes-" * 10)

    def test_rejects_path_traversal(self):
        job = {"id": "republish_job", "input": {
            "source_job_id": "../escape", "source_filename": "clip.mp4"}}
        with self.assertRaisesRegex(ValueError, "invalid source_job_id"):
            p.republish_existing_video(job, lambda cfg: None)

    def test_rejects_missing_file_and_mime(self):
        with tempfile.TemporaryDirectory() as td:
            job = {"id": "republish", "input": {
                "source_job_id": "missing", "source_filename": "video.mp4"}}
            with self.assertRaises(FileNotFoundError):
                p.republish_existing_video(job, lambda cfg: None, root=td)
            job["input"]["source_filename"] = "secret.txt"
            with self.assertRaisesRegex(ValueError, "must be"):
                p.republish_existing_video(job, lambda cfg: None, root=td)


if __name__ == "__main__":
    unittest.main()
