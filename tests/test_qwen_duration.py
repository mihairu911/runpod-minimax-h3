"""Regression: T2VA 2s must not set a QwenVL enum widget to invalid '2s'."""
import ast
import copy
import glob
import json
import pathlib
import random
import re
import time
import unittest
import uuid

SRC = pathlib.Path(__file__).resolve().parents[1] / "handler.py"


def patch_fn():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_patch")
    env = {
        "re": re, "glob": glob, "json": json, "time": time, "uuid": uuid,
        "random": random, "Path": pathlib.Path, "MINIMAX_CONFIGS": {},
        "COMFY_DIR": "/tmp/unused-comfy", "_job_style_text": lambda x: "",
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SRC), "exec"), env)
    return env["_patch"]


class QwenDurationTests(unittest.TestCase):
    def test_short_generation_keeps_short_latents_and_valid_qwen_dropdown(self):
        patch = patch_fn()
        base = {
            "105:256": {"class_type": "QwenVL_Unified_PromptEnhancer",
                        "inputs": {"duration": "5s", "passthrough": False}},
            "105:111": {"class_type": "PrimitiveFloat",
                        "inputs": {"value": 10.0}},
            "105:107": {"class_type": "ComfyMathExpression",
                        "inputs": {"expression": "max(5,round(a*24))",
                                   "values.a": ["105:111", 0]}},
        }
        for sec, expected in [(2, "5s"), (5, "5s"), (6, "10s"),
                              (11, "15s"), (20, "20s"), (25, "20s")]:
            with self.subTest(seconds=sec):
                graph = patch(copy.deepcopy(base), {
                    "seconds": sec, "seed": 20261120, "enhance": False,
                })
                self.assertEqual(graph["105:256"]["inputs"]["duration"], expected)
                self.assertEqual(graph["105:111"]["inputs"]["value"], sec)
                self.assertTrue(graph["105:256"]["inputs"]["passthrough"])
                self.assertEqual(graph["105:107"]["inputs"]["values.a"], ["105:111", 0])

if __name__ == "__main__":
    unittest.main()
