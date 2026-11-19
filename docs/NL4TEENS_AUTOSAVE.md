# N&L 4teens — RunPod AutoSave (candidate)

This branch modifies MiniMax H3's RunPod serverless handler to persist generated videos on the already mounted Global Volume.

## What changes
- MP4, WEBM and MOV are saved to `/runpod-volume/references/nl4teens/v1/test_outputs/auto/<job_id>/<filename>`.
- Video output returns only `filename`, `volume_path`, `bytes`, `sha256`, and `saved`; no MP4 base64 in the job status response.
- PNG/JPEG and other non-video outputs retain upstream handling.
- `{"input":{"action":"storage_smoke_test"}}` verifies writing and reading the volume without ComfyUI inference.
- `{"input":{"action":"health"}}` reports `autosave: direct-handler-v1` alongside upstream health fields.

## Verification
- CI: `python -m py_compile handler.py`
- CI: `python -m unittest discover -s tests -p 'test_nl4teens_autosave.py' -v`
- Push to `nl4teens-autosave` builds `ghcr.io/mihairu911/runpod-minimax-h3:autosave-test`.
- CI completion does not prove the image is pullable by RunPod or that it works on GPU. GitHub Container Registry packages may initially be private.

## Safe deployment
1. Keep production RunPod endpoint `ykr2je4xv0gmrb` unchanged.
2. Verify build success and that RunPod can pull the candidate image. Configure GHCR visibility or registry authentication as needed.
3. Create a **separate** test endpoint mounting Global Volume `cmwmmxefy000007l97ofr01ks`, with minimum workers = 0 and maximum = 1.
4. Execute `action:health`, then `action:storage_smoke_test`.
5. After these pass, execute one tiny representative generation and confirm the video exists at the returned `volume_path`, with no base64 in response.
6. Only after confirming inference and file delivery, consider switching production. Keep this PR as draft until verification.

WARNING: `volume_path` is not an HTTPS URL. MP4 delivery needs a separate read-only bridge or a signed URL.
