"""Offline regression tests for the RunPod output adapter (no GPU required)."""
import ast
import base64
import hashlib
import os
import pathlib
import re
import tempfile
import unittest

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "handler.py"


def load_output_functions():
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted = {"_nl_autosave_file", "_emit_file"}
    nodes = [x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name in wanted]
    assert {x.name for x in nodes} == wanted, "missing autosave functions"
    namespace = {
        "Path": pathlib.Path,
        "os": os,
        "re": re,
        "base64": base64,
        "INLINE_MAX": 1024,
        "INLINE_BUDGET": 4096,
        "_s3_cfg": lambda job: None,
        "S3_PREFIX": "test",
        # Output adapter test uses dummy bytes; ffprobe is tested separately
        # in tests/test_nl4teens_pipeline.py against simulated probe results.
        "inspect_video": lambda path, **kwargs: {"status": "ok"},
        "optional_delivery_cfg": lambda job: None,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace


class AutosaveTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.original = os.environ.get("NL4TEENS_OUTPUT_ROOT")
        os.environ["NL4TEENS_OUTPUT_ROOT"] = self.dir.name
        self.module = load_output_functions()

    def tearDown(self):
        if self.original is None:
            os.environ.pop("NL4TEENS_OUTPUT_ROOT", None)
        else:
            os.environ["NL4TEENS_OUTPUT_ROOT"] = self.original
        self.dir.cleanup()

    def test_video_saved_with_metadata_not_base64(self):
        data = b"fake-mp4-for-storage-test"
        output = self.module["_emit_file"]("test.mp4", data, {"id": "test:job"}, [0])
        path = pathlib.Path(output["volume_path"])
        self.assertEqual(path.read_bytes(), data)
        self.assertEqual(output["bytes"], len(data))
        self.assertEqual(output["sha256"], hashlib.sha256(data).hexdigest())
        self.assertTrue(output["saved"])
        self.assertNotIn("b64", output)
        self.assertEqual(path.parent.name, "test_job")

    def test_image_uses_original_inline_output(self):
        data = b"png"
        output = self.module["_emit_file"]("test.png", data, {"id": "test"}, [0])
        self.assertEqual(output["b64"], base64.b64encode(data).decode())

    def test_empty_video_rejected(self):
        with self.assertRaises(ValueError):
            self.module["_emit_file"]("test.mp4", b"", {"id": "test"}, [0])

    def test_smoke_action_and_health_marker(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('"storage_smoke_test"', source)
        self.assertIn('"direct-handler-v1"', source)


if __name__ == "__main__":
    unittest.main()
