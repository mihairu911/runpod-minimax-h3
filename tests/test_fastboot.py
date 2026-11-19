"""CPU-only tests for opt-in, zero-copy ComfyUI workspace preparation."""
from pathlib import Path
import importlib.util
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("prepare_workspace", ROOT / "prepare_workspace.py")
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class FastBootWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.baked = self.root / "baked"
        self.baked.mkdir()
        (self.baked / "main.py").write_text("print('comfy')\\n")
        (self.baked / "custom_nodes").mkdir()
        self.workspace = self.root / "workspace" / "ComfyUI"

    def test_zero_copy_symlink_and_write_through(self):
        self.assertEqual(MOD.prepare_workspace(self.baked, self.workspace), "created-link")
        self.assertTrue(self.workspace.is_symlink())
        self.assertEqual(self.workspace.resolve(), self.baked.resolve())
        (self.workspace / "extra_model_paths.yaml").write_text("volume: ok\\n")
        self.assertEqual((self.baked / "extra_model_paths.yaml").read_text(), "volume: ok\\n")
        self.assertEqual(MOD.prepare_workspace(self.baked, self.workspace), "existing-link")

    def test_existing_working_copy_preserved(self):
        self.workspace.mkdir(parents=True)
        (self.workspace / "main.py").write_text("original")
        self.assertEqual(MOD.prepare_workspace(self.baked, self.workspace), "existing-copy")
        self.assertFalse(self.workspace.is_symlink())

    def test_partial_workspace_does_not_get_deleted(self):
        self.workspace.mkdir(parents=True)
        (self.workspace / "important.txt").write_text("keep")
        with self.assertRaises(RuntimeError):
            MOD.prepare_workspace(self.baked, self.workspace)
        self.assertEqual((self.workspace / "important.txt").read_text(), "keep")

    def test_empty_directory_replaced_safely(self):
        self.workspace.mkdir(parents=True)
        self.assertEqual(MOD.prepare_workspace(self.baked, self.workspace), "created-link")

    def test_requires_baked_main(self):
        (self.baked / "main.py").unlink()
        with self.assertRaises(RuntimeError):
            MOD.prepare_workspace(self.baked, self.workspace)

    def test_startup_error_and_timeout_diagnostics_present(self):
        handler = (ROOT / "handler.py").read_text()
        startup = (ROOT / "serverless-entrypoint.sh").read_text()
        self.assertIn("ComfyUI workspace preparation exceeded", handler)
        self.assertIn("ComfyUI workspace preparation failed", handler)
        self.assertIn("NL4TEENS_FAST_BOOT", startup)
        self.assertIn('PREP_ERROR="${PREP_DONE}.error"', startup)


if __name__ == "__main__":
    unittest.main()
