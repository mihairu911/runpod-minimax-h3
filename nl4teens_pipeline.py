"""N&L 4teens: fail-fast model checks and verified video artifacts.

No GPU imports: helpers are unit-testable on GitHub Actions.
"""
import json
import os
import subprocess
import urllib.parse
from pathlib import Path

VIDEO_EXT = (".mp4", ".webm", ".mov")
SAVER_TYPES = {"VHS_VideoCombine", "SaveVideo", "SaveVideoAsWebm"}
MODEL_INPUTS = {
    "UNETLoader": ("unet_name",),
    "VAELoader": ("vae_name",),
    "CLIPLoader": ("clip_name",),
    "CheckpointLoaderSimple": ("ckpt_name",),
    "CheckpointLoader": ("ckpt_name",),
    "LoraLoader": ("lora_name",),
    "LoraLoaderModelOnly": ("lora_name",),
    "UpscaleModelLoader": ("model_name",),
}


def preflight_models(prompt, object_info):
    """Validate known ComfyUI model selectors against live registered choices.

    object_info(class_type) must return the JSON object from
    GET /object_info/{class_type}. Avoid global /object_info payloads.
    """
    if not isinstance(prompt, dict) or not prompt:
        raise ValueError("model preflight: empty or invalid workflow")
    checked = []
    cache = {}
    for node_id, node in prompt.items():
        cls = str(node.get("class_type", ""))
        fields = MODEL_INPUTS.get(cls)
        if not fields:
            continue
        ins = node.get("inputs") or {}
        for field in fields:
            val = ins.get(field)
            if not isinstance(val, str) or not val.strip():
                continue
            if cls not in cache:
                try:
                    info = object_info(cls)
                    cache[cls] = info.get(cls) if isinstance(info, dict) else None
                except Exception as exc:
                    raise RuntimeError(f"model preflight: cannot query ComfyUI options for {cls}") from exc
            schema = cache[cls]
            if not isinstance(schema, dict):
                raise RuntimeError(f"model preflight: missing ComfyUI object info for {cls}")
            allowed = None
            for section in ("required", "optional"):
                raw = (schema.get("input") or {}).get(section) or {}
                spec = raw.get(field)
                if isinstance(spec, (list, tuple)) and spec and isinstance(spec[0], (list, tuple)):
                    allowed = [x for x in spec[0] if isinstance(x, str)]
                    break
            if allowed is None:
                raise RuntimeError(f"model preflight: no selectable options for {cls}.{field}")
            if val not in allowed:
                examples = ", ".join(allowed[:6]) if allowed else "none installed"
                raise ValueError(
                    f"model preflight: node {node_id} ({cls}.{field}) requests '{val}', "
                    f"but installed options are: {examples}"
                )
            checked.append(f"{node_id}:{cls}.{field}")
    return {"status": "ok", "models_checked": len(checked)}


def expects_video(prompt):
    return any(
        isinstance(n, dict) and
        str(n.get("class_type", "")) in SAVER_TYPES and
        (n.get("inputs") or {}).get("save_output", True) is not False
        for n in prompt.values()
    )


def validate_video_outputs(prompt, outputs):
    if expects_video(prompt):
        vids = [x for x in (outputs or []) if
                isinstance(x, dict) and
                str(x.get("filename", "")).lower().endswith(VIDEO_EXT)]
        if not vids:
            raise RuntimeError(
                "Video output missing: ComfyUI returned no MP4/WEBM/MOV artifact. "
                "Check workflow model selectors and ComfyUI execution logs."
            )
        for item in vids:
            if item.get("saved") is not True or not item.get("volume_path"):
                raise RuntimeError("Video output exists but was not persisted to Global Volume")
    return {"status": "ok", "video_outputs": len([
        x for x in (outputs or []) if isinstance(x, dict) and
        str(x.get("filename", "")).lower().endswith(VIDEO_EXT)
    ])}


def inspect_video(path, expected_seconds=None, require_audio=False):
    """Small ffprobe-only technical QC; never loads all frames or audio in RAM."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size < 32:
        raise RuntimeError("video QC: file missing or implausibly short")
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration,size:stream=codec_name,codec_type,width,height,avg_frame_rate,sample_rate,channels",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30, check=True
        )
        result = json.loads(proc.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError,
            ValueError) as exc:
        raise RuntimeError("video QC: ffprobe validation failed") from exc
    streams = result.get("streams", [])
    video = next((x for x in streams if x.get("codec_type") == "video"), None)
    audio = next((x for x in streams if x.get("codec_type") == "audio"), None)
    if not video or int(video.get("width") or 0) <= 0 or int(video.get("height") or 0) <= 0:
        raise RuntimeError("video QC: no valid video stream")
    duration = float((result.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        raise RuntimeError("video QC: missing positive duration")
    if require_audio and not audio:
        raise RuntimeError("video QC: audio required but no audio stream exists")
    fps = video.get("avg_frame_rate") or "0/1"
    try:
        num, den = map(int, fps.split("/"))
        fps_num = round(num / den, 3) if den else 0
    except (ValueError, AttributeError):
        fps_num = 0
    return {
        "status": "ok", "duration_seconds": round(duration, 3),
        "width": video.get("width"), "height": video.get("height"),
        "fps": fps_num, "video_codec": video.get("codec_name"),
        "audio_present": bool(audio),
        "audio_codec": audio.get("codec_name") if audio else None,
        "size_bytes": path.stat().st_size,
        "duration_delta_seconds": round(duration - float(expected_seconds), 3)
        if expected_seconds is not None else None,
    }


def optional_delivery_cfg(job, env=None):
    """Use per-job S3 config or secure endpoint environment, never log secrets."""
    env = os.environ if env is None else env
    inp = job.get("input") or {}
    cfg = job.get("s3Config") or inp.get("s3Config")
    if isinstance(cfg, dict) and all(cfg.get(k) for k in
                                     ("endpointUrl", "accessId", "accessSecret", "bucketName")):
        return cfg
    mapping = {
        "endpointUrl": "NL4TEENS_S3_ENDPOINT_URL",
        "accessId": "NL4TEENS_S3_ACCESS_ID",
        "accessSecret": "NL4TEENS_S3_ACCESS_SECRET",
        "bucketName": "NL4TEENS_S3_BUCKET",
    }
    cfg = {k: env.get(v) for k, v in mapping.items()}
    if not all(cfg.values()):
        return None
    if env.get("NL4TEENS_S3_REGION"):
        cfg["region"] = env["NL4TEENS_S3_REGION"]
    return cfg


def signed_media_upload(data, filename, job, cfg, make_client, ttl=3600):
    """Upload to external S3-compatible bucket and return an expiring GET URL."""
    if cfg is None:
        return {"delivery": "volume_only"}
    safe_name = Path(filename).name
    jid = "".join(c if c.isalnum() or c in "_.-" else "_" for c in str(job.get("id") or "job"))[:100]
    key = "nl4teens/artifacts/" + jid + "/" + safe_name
    client = make_client(cfg)
    client.put_object(Bucket=cfg["bucketName"], Key=key, Body=data,
                      ContentType="video/mp4" if safe_name.lower().endswith(".mp4")
                      else "application/octet-stream")
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": cfg["bucketName"], "Key": key},
        ExpiresIn=max(60, min(int(ttl), 604800)),
    )
    return {"delivery": "signed_url", "url": url, "url_ttl_seconds": max(60, min(int(ttl), 604800))}


def r2_delivery_smoke_test(cfg, make_client, job_id, urlopen=None):
    """Write, signed-GET, compare and delete a tiny object.

    This test runs independently from ComfyUI; it must never return the signed
    URL or the access credentials to the RunPod job response.
    """
    import urllib.request
    if urlopen is None:
        urlopen = urllib.request.urlopen
    if not isinstance(cfg, dict) or not all(cfg.get(k) for k in (
            "endpointUrl", "accessId", "accessSecret", "bucketName")):
        return {"status": "not_configured", "r2_ready": False}
    host = (urllib.parse.urlparse(cfg["endpointUrl"]).hostname or "").lower()
    if not (host.endswith(".r2.cloudflarestorage.com") and
            cfg["endpointUrl"].startswith("https://")):
        raise ValueError("R2 smoke test requires a Cloudflare R2 S3 HTTPS endpoint")

    marker = b"NL4TEENS_R2_DELIVERY_SMOKE_V1"
    safe_jid = "".join(c if c.isalnum() or c in "_.-" else "_" for c in str(job_id))[:80]
    key = "nl4teens/smoke/" + safe_jid + ".txt"
    client = make_client(cfg)
    uploaded = False
    cleanup_ok = False
    try:
        client.put_object(Bucket=cfg["bucketName"], Key=key, Body=marker,
                          ContentType="text/plain")
        uploaded = True
        signed_url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": cfg["bucketName"], "Key": key},
            ExpiresIn=120,
        )
        # Explicitly check the signed GET. Readback must match the uploaded bytes.
        with urlopen(signed_url, timeout=20) as response:
            received = response.read(1024)
        if received != marker:
            raise RuntimeError("R2 smoke test readback differs from the uploaded marker")
    finally:
        if uploaded:
            client.delete_object(Bucket=cfg["bucketName"], Key=key)
            cleanup_ok = True
    return {
        "status": "ok",
        "r2_ready": True,
        "write_verified": True,
        "signed_get_verified": True,
        "temporary_object_deleted": cleanup_ok,
    }


def republish_existing_video(job, make_client, root=None):
    """Republish an already stored video to private R2, without inference.

    Staging-only opt-in in handler. Restrict source to safe basename and job ID
    under NL4TEENS_OUTPUT_ROOT; never accept absolute paths or arbitrary reads.
    """
    import hashlib
    import re
    inputs = job.get("input") or {}
    source_job_id = inputs.get("source_job_id")
    source_filename = inputs.get("source_filename")
    if not isinstance(source_job_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", source_job_id):
        raise ValueError("republish: invalid source_job_id")
    if not isinstance(source_filename, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", source_filename):
        raise ValueError("republish: invalid source_filename")
    if source_filename.lower().endswith(VIDEO_EXT) is False:
        raise ValueError("republish: source must be MP4, MOV or WEBM")
    output_root = Path(root or os.environ.get(
        "NL4TEENS_OUTPUT_ROOT",
        "/runpod-volume/references/nl4teens/v1/test_outputs/auto")).resolve()
    source = (output_root / source_job_id / source_filename).resolve()
    if not source.is_relative_to(output_root) or not source.is_file():
        raise FileNotFoundError("republish: source is missing or outside the output root")
    size = source.stat().st_size
    if size < 32 or size > 256 * 1024 * 1024:
        raise ValueError("republish: source size outside permitted range")
    qc = inspect_video(source, require_audio=bool(inputs.get("require_audio", False)))
    cfg = optional_delivery_cfg(job)
    if cfg is None:
        raise RuntimeError("republish: R2 delivery is not configured")
    data = source.read_bytes()
    delivered = signed_media_upload(
        data, source_filename, job, cfg, make_client,
        ttl=os.environ.get("NL4TEENS_S3_URL_TTL_S", "3600"))
    return {
        "status": "ok", "source_job_id": source_job_id,
        "filename": source_filename, "volume_path": str(source),
        "bytes": size, "sha256": hashlib.sha256(data).hexdigest(),
        "qc": qc, **delivered,
    }
