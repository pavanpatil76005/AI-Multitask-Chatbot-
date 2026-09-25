import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = ts.transpileModule(fs.readFileSync("src/services/api.ts", "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;

function setup(fetcher, initialToken = "expired-token") {
  let token = initialToken;
  const redirects = [];
  const exports = {};
  const localStorage = {
    getItem: () => token,
    setItem: (_key, value) => { token = value; },
    removeItem: () => { token = null; },
  };
  vm.runInNewContext(source, {
    exports, process: { env: {} }, Headers, FormData, fetch: fetcher,
    localStorage, window: { location: { replace: path => redirects.push(path) } },
  });
  return { ...exports, localStorage, redirects };
}

test("401 from chats clears rejected session and redirects to login", async () => {
  const api = setup(async () => new Response("", { status: 401 }));
  await assert.rejects(api.apiRequest("/api/chats"), { name: "SessionExpiredError" });
  assert.equal(api.localStorage.getItem(), null);
  assert.deepEqual(api.redirects, ["/login"]);
});

test("incorrect login credentials stay on the login form", async () => {
  const api = setup(async () => new Response("", { status: 401 }));
  assert.equal((await api.apiRequest("/api/auth/login")).status, 401);
  assert.deepEqual(api.redirects, []);
});

test("late unauthorized request preserves a newer login", async () => {
  let finish;
  const api = setup(() => new Promise(resolve => { finish = resolve; }));
  const request = api.apiRequest("/api/chats");
  api.localStorage.setItem("access_token", "new-token");
  finish(new Response("", { status: 401 }));
  await assert.rejects(request, { name: "SessionExpiredError" });
  assert.equal(api.localStorage.getItem(), "new-token");
  assert.deepEqual(api.redirects, []);
});

test("authenticated streaming requests share session handling", async () => {
  const api = setup(async (_url, options) => {
    assert.equal(options.headers.get("Authorization"), "Bearer expired-token");
    return new Response("", { status: 401 });
  });
  await assert.rejects(api.apiRequest("/api/chats/1/messages/stream", { method: "POST" }), { name: "SessionExpiredError" });
  assert.deepEqual(api.redirects, ["/login"]);
});

test("network errors explain which backend is unreachable", async () => {
  const api = setup(async () => { throw new TypeError("fetch failed"); });
  await assert.rejects(api.apiRequest("/api/chats"), /Cannot reach the backend at http:\/\/127.0.0.1:8001/);
  assert.deepEqual(api.redirects, []);
});

test("Stop preserves the original AbortError", async () => {
  const controller = new AbortController();
  controller.abort();
  const stopped = new DOMException("Stopped", "AbortError");
  const api = setup(async () => { throw stopped; });
  await assert.rejects(api.apiRequest("/api/chats/1/messages/stream", { signal: controller.signal }), error => error === stopped);
  assert.deepEqual(api.redirects, []);
});

test("valid sessions pass through and multipart boundary stays browser-managed", async () => {
  const api = setup(async (_url, options) => {
    assert.equal(options.headers.has("Content-Type"), false);
    assert.equal(options.headers.get("Authorization"), "Bearer valid-token");
    return new Response("[]", { status: 200 });
  }, "valid-token");
  assert.equal((await api.apiRequest("/api/files/extract", { method: "POST", body: new FormData() })).status, 200);
  assert.deepEqual(api.redirects, []);
});
