"""Prepare ComfyUI workspace without copying the full baked tree.

This is opt-in via NL4TEENS_FAST_BOOT=true in serverless-entrypoint.sh.
The baked tree is a container image path; writes through the symlink remain
isolated in the per-container overlay filesystem.
"""
from pathlib import Path
import sys


def prepare_workspace(baked: Path, destination: Path) -> str:
    baked = baked.resolve(strict=True)
    if not (baked / "main.py").is_file():
        raise RuntimeError(f"Missing baked ComfyUI main.py: {baked}")
    if destination.is_symlink():
        if destination.resolve() == baked and (destination / "main.py").is_file():
            return "existing-link"
        raise RuntimeError(f"Workspace contains a different symlink: {destination}")
    if (destination / "main.py").is_file():
        return "existing-copy"
    if destination.exists():
        if not destination.is_dir() or any(destination.iterdir()):
            raise RuntimeError(f"Workspace is incomplete and non-empty: {destination}")
        destination.rmdir()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.symlink_to(baked, target_is_directory=True)
    if not (destination / "main.py").is_file():
        raise RuntimeError("Workspace symlink failed verification")
    return "created-link"


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: prepare_workspace.py BAKED_DIR WORKSPACE_DIR")
    print("[prep] ComfyUI workspace:", prepare_workspace(Path(sys.argv[1]), Path(sys.argv[2])), flush=True)
