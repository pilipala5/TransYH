import { test } from "node:test";
import assert from "node:assert/strict";
import { normalizeBaseURL, apiError, clampState } from "../src/core";

test("normalize roots, version roots, nested gateways, full endpoints", () => {
  for (const [input, output] of [
    ["https://provider.example", "https://provider.example/v1"],
    [" https://provider.example/v1/ ", "https://provider.example/v1"],
    ["https://provider.example/v1/chat/completions/", "https://provider.example/v1"],
    ["https://gateway.example/api/openai/v1", "https://gateway.example/api/openai/v1"],
    ["http://localhost:8080", "http://localhost:8080/v1"],
    ["http://[::1]:8080/chat/completions", "http://[::1]:8080/v1"],
  ]) assert.equal(normalizeBaseURL(input), output);
});
test("reject unsafe or invalid API addresses", () => {
  for (const url of ["", "provider.example", "file:///tmp/key", "http://provider.example/v1",
    "https://name:secret@provider.example/v1", "https://provider.example?key=secret", "https://provider.example/#secret"]) {
    assert.throws(() => normalizeBaseURL(url));
  }
});
test("remote HTTP authorization is bound to one normalized service address", () => {
  const allowed="http://example.internal:8317/v1";
  assert.equal(normalizeBaseURL(allowed+"/chat/completions",allowed),allowed);
  assert.throws(()=>normalizeBaseURL("http://other.internal:8317/v1",allowed));
  assert.throws(()=>normalizeBaseURL("http://example.internal:8317/other",allowed));
  assert.throws(()=>normalizeBaseURL("http://example.internal:8318/v1",allowed));
});
test("report authentication, quota, endpoint, and server failures", () => {
  assert.match(apiError(401), /鉴权/); assert.match(apiError(403), /权限/);
  assert.match(apiError(429), /限流/); assert.match(apiError(404), /不存在/);
  assert.match(apiError(503), /不可用/);
});
test("map page bounds without changing scale or PDF coordinates", () => {
  assert.deepEqual(clampState({ pageIndex: 9, scale: "page-width", top: 256, left: 12 }, 3),
    { pageIndex: 2, scale: "page-width", top: 256, left: 12 });
});
