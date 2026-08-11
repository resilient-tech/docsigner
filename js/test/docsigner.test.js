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
