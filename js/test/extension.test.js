// Sanity checks for the extension: manifest is valid, scripts parse, icons exist.
// A real browser test is a manual step, see PLAN.md phase 3.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const extDir = fileURLToPath(new URL("../../extension/", import.meta.url));

test("manifest.json is valid and matches the contract", () => {
  const manifest = JSON.parse(readFileSync(join(extDir, "manifest.json"), "utf8"));
  assert.equal(manifest.manifest_version, 3);
  assert.ok(manifest.permissions.includes("nativeMessaging"));
  assert.ok(manifest.permissions.includes("storage"));
  assert.equal(manifest.background.service_worker, "background.js"); // Chromium
  // Chrome refuses to load MV3 manifests carrying background.scripts; the
  // Firefox event-page variant comes from scripts/build_firefox_extension.py.
  assert.equal(manifest.background.scripts, undefined);
  assert.equal(manifest.content_scripts[0].run_at, "document_start");
  assert.deepEqual(manifest.content_scripts[0].matches, ["<all_urls>"]);
  assert.equal(manifest.browser_specific_settings.gecko.id, "docsigner@docsigner.org");
});

test("extension scripts parse", () => {
  for (const file of ["content.js", "background.js", "consent.js"]) {
    execFileSync(process.execPath, ["--check", join(extDir, file)]);
  }
});

test("icons exist", () => {
  for (const size of [16, 48, 128]) {
    assert.ok(existsSync(join(extDir, "icons", `icon${size}.png`)), `icon${size}.png missing`);
  }
});
