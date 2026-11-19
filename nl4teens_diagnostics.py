"""N&L 4teens: low-overhead persistent ComfyUI/RunPod diagnostics.

Never record prompts, media bytes, API tokens or presigned URLs.
This module is intentionally stdlib-only and safe to test without a GPU.
"""
import json
import os
import re
import time
from pathlib import Path


DEFAULT_ROOT = "/runpod-volume/references/nl4teens/v1/diagnostics"


def _safe_id(raw):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(raw or "unknown"))[:120]
    return safe if safe not in ("", ".", "..") else "unknown"


def _diagnostics_root():
    root = Path(os.environ.get("NL4TEENS_DIAG_ROOT", DEFAULT_ROOT))
    # Diagnostics must be on persistent volume, never silently fallback for jobs.
    if not Path("/runpod-volume").is_dir() and "NL4TEENS_DIAG_ROOT" not in os.environ:
        return None
    try:
        root.mkdir(parents=True, exist_ok=True)
        return root
    except OSError:
        return None


def worker_comfy_log_path():
    """New per-worker durable logfile; fallback to ephemeral log if volume fails."""
    root = _diagnostics_root()
    if root is None:
        return Path("/workspace/comfy.log")
    folder = root / "workers"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        host = _safe_id(os.environ.get("HOSTNAME", "worker"))
        return folder / f"{host}-{int(time.time())}-{os.getpid()}.log"
    except OSError:
        return Path("/workspace/comfy.log")


def log_event(job_id, stage, **details):
    """Append an fsynced, bounded diagnostic event without sensitive content."""
    root = _diagnostics_root()
    if root is None:
        return False
    permitted = {
        "workflow", "seconds", "width", "height", "node_count",
        "checked_models", "prompt_id", "elapsed_seconds", "running",
        "pending", "vram_free_mib", "total_vram_mib", "error_type",
        "log_path", "note",
    }
    clean = {}
    for key, value in details.items():
        if key not in permitted:
            continue
        if key in ("workflow", "prompt_id", "error_type", "note"):
            clean[key] = _safe_id(value)[:120]
        elif key == "log_path":
            # No arbitrary paths or URLs; only show the worker log's basename.
            clean[key] = Path(str(value)).name[:180]
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            clean[key] = round(float(value), 2)
    event = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stage": _safe_id(stage),
        **clean,
    }
    try:
        path = root / "jobs" / _safe_id(job_id) / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        line = (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        with path.open("ab", buffering=0) as file:
            file.write(line)
            os.fsync(file.fileno())
        return True
    except OSError:
        return False


def queue_snapshot(get_json):
    """Returns limited GPU and queue metadata, never full prompt objects."""
    out = {"running": -1, "pending": -1}
    try:
        queue = get_json("/queue")
        out["running"] = len(queue.get("queue_running", []))
        out["pending"] = len(queue.get("queue_pending", []))
    except Exception:
        pass
    try:
        stats = get_json("/system_stats")
        devices = stats.get("devices", [])
        if devices:
            device = devices[0]
            if isinstance(device.get("vram_free"), (int, float)):
                out["vram_free_mib"] = round(device["vram_free"] / 1048576, 2)
            if isinstance(device.get("vram_total"), (int, float)):
                out["total_vram_mib"] = round(device["vram_total"] / 1048576, 2)
    except Exception:
        pass
    return out
