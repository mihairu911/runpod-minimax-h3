# N&L 4teens: Cloudflare R2 → RunPod staging

## Account and access verified

- Cloudflare R2 bucket: `nl4teens-video` (private, public `r2.dev` disabled).
- R2 API token name: `NL4teens-RunPod`, active, *bucket only*. Cloudflare permission: `Workers R2 Storage Bucket Item Write` (includes read, write and list).
- R2 lifecycle deletes `nl4teens/artifacts/` objects after 604800 seconds / 7 days.
- Cloudflare ChatGPT connector can manage R2, but its OAuth session is **not** the RunPod S3 credential and must not be used as the worker secret.
- S3 Access Key ID and Secret Access Key must be saved directly through RunPod Serverless console Environment Variables, never in chat, PRs or logs.

## Separate endpoint for safe credential testing

- Endpoint: `wdb0nu7k9dmqtr` (name `nl4teens-r2-integration-temp`), min workers `0`, max `1`. GPU `BLACKWELL_96`, Global Volume `cmwmmxefy000007l97ofr01ks`.
- Image: refresh to the latest pinned SHA digest **after** successful CI build; avoid mutable :autosave-test when possible.
- Configure the following environment variables. The first four are pre-set on staging:
  - `NL4TEENS_S3_ENDPOINT_URL=https://8c739d4b814a411d8bcacc92a4fca6d6.r2.cloudflarestorage.com`
  - `NL4TEENS_S3_BUCKET=nl4teens-video`
  - `NL4TEENS_S3_REGION=auto`
  - `NL4TEENS_S3_URL_TTL_S=3600`
- **User must set these two secrets privately in the staging endpoint Settings → Environment Variables:**
  - `NL4TEENS_S3_ACCESS_ID` = R2 `Access Key ID`
  - `NL4TEENS_S3_ACCESS_SECRET` = R2 `Secret Access Key`
- The original production endpoint `ykr2je4xv0gmrb` is **untouched** and must not be changed before the staged tests succeed.

## Test sequence (no video inference)

Run `{"input":{"action":"r2_smoke_test"}}` only **after** secrets exist on the staging endpoint with the up-to-date candidate image. The handler performs a tiny temporary upload, signed GET readback, and immediate deletion; it returns `signed_get_verified=true` without exposing signed URLs or secrets.

Then run `{"input":{"action":"health"}}` and `{"input":{"action":"storage_smoke_test"}}`. This validates storage and operational health, **not** a full real MP4 delivery. To validate a real MP4, generate one representative short clip later, confirm `output.outputs[0].delivery=signed_url`, validate the signed URL by authorized downloading, ffprobe QC and Global Volume metadata, and ensure `b64` is absent.

If Cloudflare keys have not been added or cannot be verified, stop; do not update production. The image is very large and the GPU worker's cold-start can take minutes when downloading. Keep workers min=0.

## Security and release

- No token values may be stored in GitHub, CI logs, commit messages, ChatGPT or context markdown.
- Never copy temporary signed R2 download URLs into public logs; presigned URLs grant anyone possessing them access until expiration.
- Cloudflare R2 permissions are bucket-scoped and persistent; the ChatGPT Cloudflare OAuth lifecycle is irrelevant to worker-side API access.
- After acceptance, rollout the candidate image and credentials to production with backup of v8 config; keep the PR as draft until successful acceptance.
