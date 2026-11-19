# N&L 4teens — RunPod AutoSave (candidate)

This branch modifies MiniMax H3's RunPod serverless handler to persist generated videos on the already mounted Global Volume.

## What changes
- MP4, WEBM and MOV are saved to `/runpod-volume/references/nl4teens/v1/test_outputs/auto/<job_id>/<filename>`.
- Video output returns only `filename`, `volume_path`, `bytes`, `sha256`, and `saved`; no MP4 base64 in the job status response.
- PNG/JPEG and other non-video outputs retain upstream handling.
- `{"input":{"action":"storage_smoke_test"}}` verifies writing and reading the volume without ComfyUI inference.
- `{"input":{"action":"health"}}` reports `autosave: direct-handler-v1` alongside upstream health fields.

## Faster and safer worker initialization
- Set `NL4TEENS_FAST_BOOT=true` **only on the isolated test endpoint** to symlink the baked ComfyUI tree into the workspace instead of copying it.
- The legacy copy startup is preserved when this variable is unset or false.
- Preparation now records duration and a `.error` marker on failure; the health action includes `prep_done`, `prep_error`, and `fast_boot`.
- The faster startup is not yet verified with GPU inference and may have filesystem compatibility limitations.

## Verification
- CI: `python -m py_compile handler.py prepare_workspace.py`
- CI: `bash -n serverless-entrypoint.sh`
- CI: `python -m unittest discover -s tests -p 'test_*.py' -v`
- A commit containing `[build]` (or manual dispatch) builds `ghcr.io/mihairu911/runpod-minimax-h3:autosave-test`.
- CI completion does not prove the image is pullable by RunPod or that it works on GPU. The candidate registry image was publicly pullable in the prior audit, but each new digest must still be checked.

## Safe deployment
1. Keep production RunPod endpoint `ykr2je4xv0gmrb` unchanged.
2. Verify build success and that RunPod can pull the candidate image. Configure GHCR visibility or registry authentication as needed.
3. Create a **separate** test endpoint mounting Global Volume `cmwmmxefy000007l97ofr01ks`, with minimum workers = 0 and maximum = 1.
4. Set `NL4TEENS_FAST_BOOT=true` and `VOLUME_AUTOPOPULATE=false` only for this isolated endpoint. Execute `action:health`, then `action:storage_smoke_test`. Check the new preparation diagnostics.
5. After these pass, execute one tiny representative generation and confirm the video exists at the returned `volume_path`, with no base64 in response.
6. Only after confirming inference and file delivery, consider switching production. Keep this PR as draft until verification.

WARNING: `volume_path` is not an HTTPS URL. MP4 delivery needs a separate read-only bridge or a signed URL.

## Safety checks before rendering (new)

- After the workflow has been patched with node parameters, `preflight_models` queries ComfyUI's **live** `/object_info/<class_type>` for known model selectors (UNETLoader, CLIPLoader, VAELoader, checkpoint, LoRA and upscaler loaders).
- If a requested model is absent from the worker's registered choices, the job **fails before entering the GPU rendering queue**, reporting the missing file and a few available names. ComfyUI must still be running to serve the metadata; this is not a zero-cost preflight after a cold start.
- Optional explicit check: `{"input":{"action":"preflight","workflow":"MiniMaxH3-Turbo-T2VA.json","params":{"105:6:unet_name":"minimax_h3_fl2va_pruned_int8_convrot.safetensors"}}}` returns the checked-model count without queuing generation. The model file must be installed in the attached volume.
- Workflows with an enabled video saver must return at least one real MP4/MOV/WEBM. A zero-output result now raises an error rather than returning a misleading `COMPLETED` status.
- Each saved video is checked via `ffprobe`: duration, size, FPS, video codec, audio presence and audio codec. Malformed videos are reported as failed. Set `require_audio=true` in the job input to require an audio track. `storage_smoke_test` uses synthetic bytes and deliberately bypasses `ffprobe`.

## Video delivery: optional external S3-compatible storage

**RunPod Global Volume has no direct S3 endpoint:** https://docs.runpod.io/storage/s3-api (the RunPod S3 API supports network volumes, not global volumes). The video remains on Global Volume whether or not external delivery is enabled.

For a short-lived download link, optionally configure a **private external S3-compatible bucket** (AWS S3, R2, etc.) using secure RunPod endpoint environment variables:

- `NL4TEENS_S3_ENDPOINT_URL` — S3 API endpoint (for AWS, use the appropriate regional endpoint)
- `NL4TEENS_S3_BUCKET` — private bucket
- `NL4TEENS_S3_ACCESS_ID` — access ID
- `NL4TEENS_S3_ACCESS_SECRET` — access secret; **do not place in GitHub, logs, workflow YAML, or chat**
- `NL4TEENS_S3_URL_TTL_S` — expiration seconds, default 3600

Alternatively, supply an explicit `s3Config` object in a secure job request if that workflow supports it. When configured, the handler uploads the already-saved MP4 and returns `delivery=signed_url`, a temporary `url`, and the expiration. With no storage credentials it returns `delivery=volume_only`, **not** a fabricated public link.

An optional upload failure returns `delivery=upload_failed` while keeping the volume copy. Set `require_delivery=true` to fail the job if the additional upload is mandatory. Keep the object bucket private. Avoid publishing MP4s or private credentials through GitHub Actions.

This implementation is **not yet integration-tested against an external S3 bucket** and does not turn the Global Volume path into an HTTP URL.

## Production rollout acceptance

1. CI must pass all unit tests and Docker overlay build must finish.
2. On an **isolated** Serverless endpoint, run `action=health` and `action=storage_smoke_test`.
3. Run `action=preflight` first with a deliberately missing model (expect FAILED) and then the real installed model (expect PASSED).
4. Only after this, run one short representative MP4 render and inspect its `qc` object, file sha256 and volume path; it must not have a `b64` field.
5. If an external bucket is available, check that the signed link downloads and expires on schedule; do not claim delivery works without this check.
6. Do not merge draft PR or switch production image until the above checks pass; rollback is the original production image and environment.
