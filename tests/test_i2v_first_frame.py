"""I2VA input safety and first-frame conditioning contract (no GPU)."""
import ast
import copy
import json
import os
import pathlib
import re
import glob
import random
import tempfile
import time
import unittest
import uuid

from nl4teens_pipeline import validated_reference_image

SRC = pathlib.Path(__file__).resolve().parents[1] / "handler.py"


def patch_fn(captured):
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_patch")
    env = {
        "re": re, "glob": glob, "json": json, "time": time, "uuid": uuid,
        "random": random, "Path": pathlib.Path, "MINIMAX_CONFIGS": {},
        "COMFY_DIR": "/tmp/unused-comfy", "_job_style_text": lambda x: "",
        "validated_reference_image": lambda path: b"RIFFxxxxxxxxWEBP" + b"0" * 5000,
        "_upload": lambda name, data: captured.append((name, data)) or name,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SRC), "exec"), env)
    return env["_patch"]


class I2VFirstFrameTests(unittest.TestCase):
    def test_real_first_frame_is_loaded_and_pixaroma_state_remains_json(self):
        captures = []
        patch = patch_fn(captures)
        state = {"version": 1, "mode": "off", "orig_name": "stale-demo.jpg",
                 "max_mp": 1, "longest_side": 1024}
        graph = {
            "256": {"class_type": "PixaromaLoadImageMini",
                    "inputs": {"image": "stale-demo.jpg",
                               "LoadImageMiniState": json.dumps(state)}},
            "105:104": {"class_type": "MiniMaxH3ImageToVideo",
                        "inputs": {"first_frame": ["205", 2], "length": ["105:107", 1]}},
            "205": {"class_type": "ComfyUI-PerfectVideoResolution",
                    "inputs": {"image": ["256", 0], "use_image_aspect": True,
                               "resolution": "Native — 1344×768"}},
            "105:111": {"class_type": "PrimitiveFloat", "inputs": {"value": 5}},
            "105:107": {"class_type": "ComfyMathExpression",
                        "inputs": {"expression": "max(5,round(a*24))", "values.a": ["105:111", 0]}},
        }
        final = patch(copy.deepcopy(graph), {
            "first_frame_path": "inputs/shtab_test7_firstframe.webp",
            "video_size": "576x1024", "seconds": 5, "seed": 42,
            "enhance": False, "upscale": False, "rife": False
        })
        self.assertEqual(len(captures), 1)
        name, data = captures[0]
        self.assertTrue(name.endswith("_firstframe.webp"))
        self.assertTrue(data.startswith(b"RIFF"))
        self.assertEqual(final["256"]["inputs"]["image"], name)
        state_now = json.loads(final["256"]["inputs"]["LoadImageMiniState"])
        self.assertEqual(state_now["orig_name"], name)
        self.assertEqual(state_now["mode"], "off")
        self.assertEqual(final["205"]["inputs"]["resolution"], "576x1024")
        self.assertFalse(final["205"]["inputs"]["use_image_aspect"])
        self.assertEqual(final["105:111"]["inputs"]["value"], 5)
        self.assertEqual(final["105:104"]["inputs"]["first_frame"], ["205", 2])

    def test_i2va_rejects_missing_image_instead_of_stale_demo(self):
        with self.assertRaisesRegex(ValueError, "explicit first-frame"):
            patch_fn([])({"256": {"class_type": "PixaromaLoadImageMini",
                                    "inputs": {"image": "demo.jpg"}},
                           "105:104": {"class_type": "MiniMaxH3ImageToVideo",
                                       "inputs": {}}}, {"seconds": 5})

    def test_volume_reference_file_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            for path in ("/etc/passwd", "../private.jpg", "inputs/../escape.jpg",
                         "characters/mark.jpg", "inputs/https:evil.png"):
                with self.subTest(path=path):
                    with self.assertRaisesRegex(ValueError, "invalid relative"):
                        validated_reference_image(path, root=td)

    def test_volume_reference_file_reads_webp(self):
        with tempfile.TemporaryDirectory() as td:
            folder = pathlib.Path(td) / "inputs"
            folder.mkdir()
            path = folder / "shtab_test7_firstframe.webp"
            payload = b"RIFF" + b"0" * 4 + b"WEBP" + b"1" * 2000
            path.write_bytes(payload)
            self.assertEqual(validated_reference_image("inputs/shtab_test7_firstframe.webp", root=td), payload)

    def test_volume_reference_file_rejects_non_image_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            folder = pathlib.Path(td) / "inputs"
            folder.mkdir()
            (folder / "fake.jpg").write_bytes(b"hello" * 300)
            with self.assertRaisesRegex(ValueError, "magic"):
                validated_reference_image("inputs/fake.jpg", root=td)

    def test_symlink_outside_ref_root_does_not_leak(self):
        with tempfile.TemporaryDirectory() as td:
            folder = pathlib.Path(td) / "inputs"
            folder.mkdir()
            outside = pathlib.Path(td).parent / ("nl4teens_outside_" + str(os.getpid()) + ".jpg")
            outside.write_bytes(b"\\xff\\xd8\\xff" + b"x" * 2000)
            try:
                (folder / "shtab.jpg").symlink_to(outside)
                with self.assertRaises(FileNotFoundError):
                    validated_reference_image("inputs/shtab.jpg", root=td)
            finally:
                outside.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
