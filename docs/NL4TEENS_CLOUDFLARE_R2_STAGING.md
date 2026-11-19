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


## Post-timeout video delivery validation (2026-11-20)

The isolated real T2VA job `5fe10af6-14fa-4d97-9196-c292d5684cfb-u1` hit its 900-second execution limit and returned `FAILED: executionTimeout exceeded`. No new MP4 exists under its autosave directory and no R2 artifact was uploaded. This does **not** negate the successful prior S3 smoke test.

An earlier **valid and independently checksum-verified** video remains on Global Volume:

- Source job: `0f42bcac-49c9-4091-af0b-38f7b1bcad0d-u2`
- Filename: `MMH3_T2VA_2026-11-19_00001-audio.mp4`
- Size: 976195 bytes, SHA-256: `ff24d4d786b4ce1624fc806df4fd3be61a7050113a3f4ef868f83f70b3e0acb1`

To verify the private S3 video delivery path **without another inference**, the handler now has a staging-gated `action=r2_republish_existing` that reads only videos from `NL4TEENS_OUTPUT_ROOT/<source_job_id>/<source_filename>`, applies ffprobe QC and uploads to R2. The test handler accepts **only the one verified fixture below** when the bucket is `nl4teens-video` and fast boot is on. No environment secret migration or additional flag is needed. Any other file requires explicit `NL4TEENS_ALLOW_REPUBLISH_EXISTING=true`. Submit:

```json
{"input":{"action":"r2_republish_existing",
          "source_job_id":"0f42bcac-49c9-4091-af0b-38f7b1bcad0d-u2",
          "source_filename":"MMH3_T2VA_2026-11-19_00001-audio.mp4",
          "require_audio":true}}
```

This operation returns temporary S3 signed GET URL and the prior MP4 QC, and must not modify the source video. Never log or commit the signed URL. Default on production: `NL4TEENS_ALLOW_REPUBLISH_EXISTING=false`. A successful republish does NOT establish successful new video inference; resolve 900s timeout separately.
