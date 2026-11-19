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
