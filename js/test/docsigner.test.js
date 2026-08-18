// Unit tests for DocSigner against a fake window. Run: node --test
// The "extension" here is just a listener answering request events.

import { test } from "node:test";
import assert from "node:assert/strict";

if (typeof globalThis.CustomEvent !== "function") {
  globalThis.CustomEvent = class CustomEvent extends Event {
    constructor(type, options = {}) {
      super(type, options);
      this.detail = options.detail ?? null;
    }
  };
}
globalThis.window = new EventTarget();

const { DocSigner, DocSignerError } = await import("../docsigner.js");

const REQUEST_EVENT = "org.docsigner.request";
const RESPONSE_EVENT = "org.docsigner.response";

// Installs a fake extension. handler(command, params) returns
// {result} or {error}, or null to stay silent. Returns an uninstall function.
function fakeExtension(handler) {
  const listener = (event) => {
    const { requestId, command, params } = event.detail;
    const reply = handler(command, params);
    if (!reply) return;
    queueMicrotask(() => {
      window.dispatchEvent(new CustomEvent(RESPONSE_EVENT, { detail: { requestId, ...reply } }));
    });
  };
  window.addEventListener(REQUEST_EVENT, listener);
  return () => window.removeEventListener(REQUEST_EVENT, listener);
}

test("init resolves on ping response", async (t) => {
  t.after(fakeExtension((command) =>
    command === "ping" ? { result: { installed: true, version: "0.1.0" } } : null
  ));
  const signer = new DocSigner();
  assert.deepEqual(await signer.init({ timeout: 200 }), { installed: true, version: "0.1.0" });
});

test("init times out with EXTENSION_NOT_INSTALLED when nobody answers", async () => {
  const signer = new DocSigner();
  await assert.rejects(signer.init({ timeout: 30 }), (e) => {
    assert.ok(e instanceof DocSignerError);
    assert.equal(e.code, "EXTENSION_NOT_INSTALLED");
    return true;
  });
});

test("status reports both versions when everything is installed", async (t) => {
  t.after(fakeExtension((command) => {
    if (command === "ping") return { result: { installed: true, version: "0.2.0" } };
    if (command === "getVersion") return { result: { version: "0.3.1", protocolVersion: 1 } };
    return null;
  }));
  const signer = new DocSigner();
  assert.deepEqual(await signer.status({ timeout: 200 }), {
    extension: "0.2.0", host: "0.3.1", downloadUrl: null, error: null,
  });
});

test("status offers a download when the extension is missing", async () => {
  const signer = new DocSigner();
  const state = await signer.status({ timeout: 30 });
  assert.equal(state.extension, null);
  assert.equal(state.host, null);
  assert.equal(state.error.code, "EXTENSION_NOT_INSTALLED");
  assert.match(state.downloadUrl, /^https:\/\//);
});

test("status offers a download when the host is missing", async (t) => {
  t.after(fakeExtension((command) => {
    if (command === "ping") return { result: { installed: true, version: "0.2.0" } };
    // What background.js sends: the code plus where to get the missing piece.
    return { error: {
      code: "HOST_NOT_INSTALLED",
      message: "The DocSigner native host is not installed",
      downloadUrl: "https://example.test/download#web",
    } };
  }));
  const signer = new DocSigner();
  const state = await signer.status({ timeout: 200 });
  assert.equal(state.extension, "0.2.0");
  assert.equal(state.host, null);
  assert.equal(state.downloadUrl, "https://example.test/download#web");
  assert.equal(state.error.code, "HOST_NOT_INSTALLED");
});

test("status keeps a broken host apart from a missing one", async (t) => {
  t.after(fakeExtension((command) =>
    command === "ping"
      ? { result: { installed: true, version: "0.2.0" } }
      : { error: { code: "MODULE_ERROR", message: "driver blew up" } }
  ));
  const signer = new DocSigner();
  const state = await signer.status({ timeout: 200 });
  assert.equal(state.host, null);
  assert.equal(state.error.code, "MODULE_ERROR");
  assert.equal(state.downloadUrl, null); // installing it again fixes nothing
});

test("a custom downloadUrl replaces the published one", async () => {
  const signer = new DocSigner({ downloadUrl: "https://intranet.test/docsigner" });
  const state = await signer.status({ timeout: 30 });
  assert.equal(state.downloadUrl, "https://intranet.test/docsigner");
});

test("listCertificates round trip returns certificates and readers", async (t) => {
  const cert = { thumbprint: "ab12", subject: "CN=Test", certificate: "aGk=" };
  t.after(fakeExtension((command) =>
    command === "listCertificates" ? { result: { certificates: [cert] } } : null
  ));
  const signer = new DocSigner();
  assert.deepEqual(await signer.listCertificates(),
    { certificates: [cert], readers: [], diagnostics: null });
});

test("listCertificates passes readers and diagnostics through", async (t) => {
  const reader = { name: "WD ProxKey 0", token: "WatchData ProxKey", driverFound: false };
  const diagnostics = { modulesConfigured: 0, modulesLoaded: 0, tokens: 0,
    pkcs11Certificates: 0, osStoreCertificates: 0 };
  t.after(fakeExtension((command) =>
    command === "listCertificates"
      ? { result: { certificates: [], readers: [reader], diagnostics } } : null
  ));
  const signer = new DocSigner();
  assert.deepEqual(await signer.listCertificates(),
    { certificates: [], readers: [reader], diagnostics });
});

test("errors propagate with code and message intact", async (t) => {
  t.after(fakeExtension(() => ({ error: { code: "PIN_LOCKED", message: "PIN retry count exhausted" } })));
  const signer = new DocSigner();
  await assert.rejects(
    signer.signHash({ thumbprint: "ab12", hashes: ["aGk="] }),
    (e) => {
      assert.ok(e instanceof DocSignerError);
      assert.equal(e.code, "PIN_LOCKED");
      assert.equal(e.message, "PIN retry count exhausted");
      return true;
    }
  );
});

test("concurrent calls route responses by requestId, even out of order", async (t) => {
  const seen = [];
  const listener = (event) => seen.push(event.detail);
  window.addEventListener(REQUEST_EVENT, listener);
  t.after(() => window.removeEventListener(REQUEST_EVENT, listener));

  const signer = new DocSigner();
  const first = signer.signHash({ thumbprint: "aa", hashes: ["one"] });
  const second = signer.signHash({ thumbprint: "bb", hashes: ["two"] });
  assert.equal(seen.length, 2);

  // Answer the second request first.
  for (const detail of [seen[1], seen[0]]) {
    window.dispatchEvent(new CustomEvent(RESPONSE_EVENT, {
      detail: { requestId: detail.requestId, result: { signatures: [detail.params.hashes[0] + "-signed"] } },
    }));
  }

  assert.deepEqual(await first, { signatures: ["one-signed"] });
  assert.deepEqual(await second, { signatures: ["two-signed"] });
});

test("digestAlgorithm defaults to sha256", async (t) => {
  let sent = null;
  t.after(fakeExtension((command, params) => {
    sent = params;
    return { result: { signatures: [] } };
  }));
  const signer = new DocSigner();
  await signer.signHash({ thumbprint: "aa", hashes: ["x"] });
  assert.equal(sent.digestAlgorithm, "sha256");
});
