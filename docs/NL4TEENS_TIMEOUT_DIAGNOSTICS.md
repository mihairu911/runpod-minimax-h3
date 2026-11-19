# N&L 4teens — MiniMax H3 render timeout diagnostics

Date: 2026-11-20. Status: instrumentation committed and CI unit-tested; no GPU test yet.

## Is a 15-minute inference time limit insufficient?

**Yes, plausible, but not confirmed.** The stage T2VA job
`5fe10af6-14fa-4d97-9196-c292d5684cfb-u1` failed at approximately
900.4 seconds with `executionTimeout exceeded`, on endpoint
`wdb0nu7k9dmqtr` configured with **RunPod Serverless execution timeout
900000 ms** and **`JOB_TIMEOUT_S=900`**. The external RunPod timeout
can kill the worker before the internal ComfyUI polling loop returns a
diagnostic error, and the outer execution time includes the
handler/ComfyUI startup, model loading, etc., not solely sampler time.
No MP4 was saved for that job.

On current ForgeHub `workflows/MiniMaxH3-Turbo-T2VA.json`, duration
is driven by `PrimitiveFloat` node `105:111` and expression node
`105:107`:
`max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17`.
For requested **5 seconds** this computes **124 frames**. Requested **2 seconds**
computes **56 frames**. The sampler has eight steps. The previously
failed test used `video_size=576x1024`, `upscale=false`,
`rife=false`, `enhance=false`. Handler rewires around postprocess,
so extra ESRGAN/RIFE should not be the cause. Other possibilities are
slow or stuck model initialization, memory pressure, an unobserved
ComfyUI node error, or unusually slow sampling. Do not assert which
until live logs confirm it.

## Diagnostic improvement: no paid GPUs for deploying code

1. ComfyUI stdout/stderr is now written, unbuffered, to a **per-worker
   persistent file**:
   `/runpod-volume/references/nl4teens/v1/diagnostics/workers/<worker>-<timestamp>-<pid>.log`
   (ephemeral `/workspace/comfy.log` fallback if volume absent).
2. After RunPod handler receives a real video job, it records sanitized
   `received`, `comfy_ready`, `preflight_ok`, `queued`, `heartbeat`
   every ~20 seconds, `comfy_finished`/`comfy_error`/`comfy_timeout`/
   `cancelled`, and `completed` stages to
   `/runpod-volume/references/nl4teens/v1/diagnostics/jobs/<job-id>/events.jsonl`.
3. Heartbeats include elapsed time, counts of queue running and pending,
   and reported VRAM totals/free. Full prompts, S3 credentials, bearer
   tokens and generated video bytes are deliberately excluded from the
   **structured** journal. The raw ComfyUI log may contain private
   prompts or filenames; keep the Global Volume private and treat logs
   as sensitive. Do not publish logs to GitHub or public R2.
4. The event journal uses immediate append and fsync so a hard worker kill
   should leave recent heartbeat entries. If storage write fails the
   render does not fail because of diagnostics alone.
5. CI checks `nl4teens_diagnostics.py` and no-GPU tests. This change
   does **not** resolve the render bottleneck by itself.

## Next controlled inference test (not yet run)

- **Do not update production** `ykr2je4xv0gmrb`. Test only staging
  `wdb0nu7k9dmqtr`, whose workers are currently `min=0,max=0`.
- Publish verified diagnostic overlay digest via CI then update **only
  staging's image**. Run `health` and `preflight`; do not alter R2
  secret variables.
- Choose a **2-second, 480x832 or 576x1024** T2VA prompt, seed fixed,
  `enhance=false`, `upscale=false`, `rife=false`,
  `require_audio=true`, `require_delivery=true`. 2s means about 56
  model frames; 5s means about 124.
- If a larger execution window is authorized, configure **both**
  `JOB_TIMEOUT_S` and outer RunPod endpoint `timeout`, leaving a
  **safety margin** for boot, upload and finalization. Do not set
  both to the same duration. Cap number of tests and GPU budget.
  Changing S3 env by automation may involve exposing persisted secrets;
  configure sensitive env directly in the RunPod dashboard.
- Follow `events.jsonl` during rendering. The worker logfile should
  identify the last running node and sample/progress output. A heartbeat
  with queue_running=1 doesn't establish productive progress; it must
  be cross-checked with recent log lines/step progress.
- On finish, independently validate MP4 through R2/Worker HTTP, QC and
  SHA256 as done in the earlier successful **republish** test.
- Stop and diagnose if GPU VRAM repeatedly approaches 0, queue status
  stops changing, ComfyUI has exception/OOM, or there is no expected
  sampling activity. Distinguish these from merely slow sampling.
- End by setting staging `workers.min=0,max=0`, deleting temporary
  CPU Pod if used, logging results in draft PR #1, and refreshing
  ACTIVE CONTEXT.

## Compatibility and rollback

New helper: `nl4teens_diagnostics.py`. Included in both Dockerfiles
and the CI compile/test jobs. The old production image is unchanged.
Do not merge the candidate PR or switch production until a fresh
generation completes end-to-end.


## Five-second run: per-job ComfyUI timeout experiment (2026-11-20)

Two-second MiniMax H3 T2VA **succeeded** on staging v6 with a QwenVL duration override, executing for 502.9s total and 483.7s inside ComfyUI. Delivery of the NEW 359245-byte H.264/AAC clip through private R2 and Cloudflare Worker was independently verified via 200 full GET, 200 GET with `utm_source=chatgpt.com`, and Range 206 with matching SHA256. The original five-second run had hit 900s, so a longer window is justified for ONE diagnostic test.

The current staging v7 image automatically clamps the QwenVL text-enhancer `duration` dropdown to one of `5s/10s/15s/20s` while preserving the requested video duration. The environment still contains `JOB_TIMEOUT_S=900`, and it must NOT be replaced through a full env patch because the staging environment contains nonexportable R2 credentials.

New handler accepts an optional **per-job** `input.comfy_timeout_s` (clamped to 60..3600 seconds). The value changes only the internal ComfyUI polling deadline, without reading or rewriting endpoint environment. Use `comfy_timeout_s=1800` (30m), outer endpoint timeout 2100000 ms (35m), single worker min=0/max=1, explicit 5s/576x1024/T2VA, `enhance=false,upscale=false,rife=false`, `require_audio=true,require_delivery=true`. Existing volume journal and Worker download verification remain enabled.

**Budget:** at most one 5-second paid GPU inference, maximum 35m execution, and immediate cleanup staging max=0 and any CPU diagnostic Pod. No production changes. If the render still fails, inspect per-job events and ComfyUI log before resubmitting. Never log API secrets or temporary Worker bearer links in a public repository.
