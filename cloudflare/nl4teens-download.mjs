// N&L 4teens: private R2 video delivery through expiring bearer-link metadata.
// Token is a 256-bit random URL-safe capability created by trusted RunPod.
// Cloudflare/ChatGPT may append query parameters; authorization NEVER depends on them.
const TOKEN = /^[A-Za-z0-9_-]{43}$/;
const ARTIFACT_KEY = /^nl4teens\/artifacts\/[A-Za-z0-9_.-]{1,120}\/[A-Za-z0-9_.-]{1,200}\.(?:mp4|mov|webm)$/i;
const BASE_HEADERS = {
  "Cache-Control": "private, no-store, max-age=0",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "X-Robots-Tag": "noindex, nofollow, noarchive",
};

const noFile = () => new Response("Not found", { status: 404, headers: BASE_HEADERS });

export async function handleDownload(request, bucket, clock = () => Date.now()) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return new Response("Method not allowed", {
      status: 405, headers: { ...BASE_HEADERS, Allow: "GET, HEAD" },
    });
  }
  const url = new URL(request.url);
  if (url.pathname === "/health") {
    return Response.json({ status: "ok", service: "nl4teens-private-download" },
      { headers: BASE_HEADERS });
  }
  const match = /^\/v\/([A-Za-z0-9_-]{43})(?:\/([A-Za-z0-9_.-]{1,200}))?$/.exec(url.pathname);
  if (!match || !TOKEN.test(match[1])) return noFile();

  // UTM / tracking query values are intentionally ignored. A link grants
  // access solely through an unguessable path token and an R2 sidecar.
  let meta;
  try {
    const sidecar = await bucket.get(`nl4teens/links/${match[1]}.json`);
    if (!sidecar || sidecar.size > 2048) return noFile();
    meta = JSON.parse(await sidecar.text());
  } catch {
    return noFile();
  }
  const nowSec = Math.floor(clock() / 1000);
  if (!meta || meta.v !== 1 ||
      !Number.isSafeInteger(meta.expiresAt) ||
      meta.expiresAt <= nowSec ||
      meta.expiresAt > nowSec + 86400 ||
      typeof meta.key !== "string" ||
      !ARTIFACT_KEY.test(meta.key)) return noFile();

  const fileName = meta.key.split("/").at(-1);
  if (match[2] && match[2] !== fileName) return noFile();

  let object;
  try {
    object = await bucket.get(meta.key, { range: request.headers });
  } catch {
    return noFile();
  }
  if (!object) return noFile();

  const headers = new Headers(BASE_HEADERS);
  object.writeHttpMetadata(headers);
  headers.set("Content-Type", fileName.endsWith(".webm") ? "video/webm" :
    fileName.endsWith(".mov") ? "video/quicktime" : "video/mp4");
  headers.set("Content-Disposition", `inline; filename="${fileName}"`);
  headers.set("Accept-Ranges", "bytes");
  headers.set("ETag", object.httpEtag);
  let status = 200;
  if (request.headers.has("range") && object.range &&
      Number.isInteger(object.range.offset) &&
      Number.isInteger(object.range.length)) {
    const { offset, length } = object.range;
    headers.set("Content-Range", `bytes ${offset}-${offset + length - 1}/${object.size}`);
    headers.set("Content-Length", String(length));
    status = 206;
  } else {
    headers.set("Content-Length", String(object.size));
  }
  return new Response(request.method === "HEAD" ? null : object.body, { status, headers });
}

export default {
  async fetch(request, env) {
    return handleDownload(request, env.VIDEOS);
  },
};
