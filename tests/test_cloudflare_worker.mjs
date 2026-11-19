import test from "node:test";
import assert from "node:assert/strict";
import { handleDownload } from "../cloudflare/nl4teens-download.mjs";

const token = "A".repeat(43);
const filename = "reference.mp4";
const key = "nl4teens/artifacts/old_job/reference.mp4";
const clock = () => 1773960000000;
const seconds = Math.floor(clock()/1000);
const meta = {v:1,expiresAt:seconds+3600,key};
const sample = new Uint8Array([0,0,0,12,102,116,121,112,0,0]);
function bucket(opts={}) {
  const calls=[];
  return {
    calls,
    async get(k, extra={}) {
      calls.push({key:k, range:extra.range?.get?.("range")});
      if (k===`nl4teens/links/${token}.json` && !opts.noMeta) {
        const info=opts.metadata??meta;
        return {size:160, text:async()=>JSON.stringify(info)};
      }
      if (k===key&&!opts.noVideo) {
        const hdr=extra.range?.get?.("range");
        const isRange=hdr==="bytes=0-3";
        return {
          size:sample.length,body:isRange?sample.slice(0,4):sample,
          httpEtag:'"checksum"',
          ...(isRange?{range:{offset:0,length:4}}:{}),
          writeHttpMetadata(h){h.set("Content-Type","video/mp4");}
        };
      }
      return null;
    }
  };
}
const link=(suffix="",tok=token)=>`https://nl4teens-download.example.workers.dev/v/${tok}/${filename}${suffix}`;

test("valid secure token streams video even when ChatGPT appends utm_source", async()=>{
  const b=bucket();
  const res=await handleDownload(new Request(link("?utm_source=chatgpt.com&hello=world")),b,clock);
  assert.equal(res.status,200);
  assert.equal(res.headers.get("Cache-Control"),"private, no-store, max-age=0");
  assert.equal(res.headers.get("Content-Type"),"video/mp4");
  assert.deepEqual(new Uint8Array(await res.arrayBuffer()),sample);
  assert.equal(b.calls.length,2);
});

test("missing or expired token cannot read video", async()=>{
  for(const b of [bucket({noMeta:true}), bucket({metadata:{...meta,expiresAt:seconds-1}})]){
    const r=await handleDownload(new Request(link()),b,clock);
    assert.equal(r.status,404);
    assert.equal(b.calls.length,1);
  }
});

test("invalid paths fail closed without R2 reads", async()=>{
  const b=bucket();
  for(const u of [link("", "B".repeat(20)), link().replace(filename,"other.mp4"),"https://example.workers.dev/nl4teens/artifacts/old_job/reference.mp4"]){
    const r=await handleDownload(new Request(u),b,clock);
    assert.equal(r.status,404);
  }
  assert.equal(b.calls.length,1);
});

test("refuse sidecar pointing outside configured artifacts", async()=>{
  const b=bucket({metadata:{v:1,expiresAt:seconds+3600,key:"secret/hidden.mp4"}});
  const r=await handleDownload(new Request(link()),b,clock);
  assert.equal(r.status,404);
  assert.equal(b.calls.length,1);
});

test("video byte ranges stream with 206 and Content-Range", async()=>{
  const b=bucket();
  const r=await handleDownload(new Request(link(),{headers:{Range:"bytes=0-3"}}),b,clock);
  assert.equal(r.status,206);
  assert.equal(r.headers.get("Content-Range"),"bytes 0-3/10");
  assert.equal(r.headers.get("Content-Length"),"4");
  assert.equal((await r.arrayBuffer()).byteLength,4);
});

test("HEAD never sends body; no listing and writes",async()=>{
  const b=bucket();
  const r=await handleDownload(new Request(link(),{method:"HEAD"}),b,clock);
  assert.equal(r.status,200);
  assert.equal(r.body,null);
  const wrong=await handleDownload(new Request(link(),{method:"POST"}),b,clock);
  assert.equal(wrong.status,405);
});

test("healthy endpoint returns no R2 data",async()=>{
  const b=bucket();
  const r=await handleDownload(new Request("https://example.workers.dev/health"),b,clock);
  assert.equal(r.status,200);
  assert.equal(b.calls.length,0);
});
