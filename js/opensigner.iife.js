// Generated from opensigner.js by build-iife.js. Do not edit by hand.
(() => {
// OpenSigner page library (CONTRACTS.md section 4).
// Talks to the browser extension over window CustomEvents, nothing else.
// Zero dependencies. ES module; opensigner.iife.js is generated from this file.

const REQUEST_EVENT = "org.opensigner.request";
const RESPONSE_EVENT = "org.opensigner.response";

/**
 * Error raised by every rejected OpenSigner promise.
 * `code` is one of the stable codes from CONTRACTS.md sections 2 and 3,
 * e.g. EXTENSION_NOT_INSTALLED, HOST_NOT_INSTALLED, ORIGIN_DENIED,
 * USER_CANCELLED, PIN_INCORRECT, PIN_LOCKED, TOKEN_NOT_FOUND, CERT_NOT_FOUND,
 * MODULE_ERROR, UNSUPPORTED, INTERNAL.
 */
class OpenSignerError extends Error {
  constructor(code, message) {
    super(message || code);
    this.name = "OpenSignerError";
    this.code = code;
  }
}

class OpenSigner {
  constructor() {
    this._pending = new Map(); // requestId -> {resolve, reject, timer}
    this._onResponse = null;
  }

  /**
   * Check that the extension is installed and answering.
   * @param {{timeout?: number}} [options] milliseconds to wait for the ping
   *   reply, default 2000.
   * @returns {Promise<{installed: boolean, version: string}>}
   *   Rejects with OpenSignerError code EXTENSION_NOT_INSTALLED on timeout.
   */
  init({ timeout = 2000 } = {}) {
    return this._call("ping", {}, {
      timeoutMs: timeout,
      timeoutCode: "EXTENSION_NOT_INSTALLED",
      timeoutMessage: `The OpenSigner extension did not answer within ${timeout} ms. It is probably not installed.`,
    });
  }

  /**
   * List certificates on all connected tokens and smartcards.
   * @returns {Promise<Array<object>>} certificate descriptors as defined in
   *   CONTRACTS.md section 2: thumbprint, certificate (b64 DER), subject,
   *   issuer, validFrom, validTo, keyType, tokenLabel, moduleName.
   */
  async listCertificates() {
    const result = await this._call("listCertificates", {});
    return result.certificates || [];
  }

  /**
   * Sign one or more digests with a token-held private key. The native host
   * prompts for the PIN; all hashes in one call cost one PIN prompt.
   * @param {{thumbprint: string, hashes: string[], digestAlgorithm?: string}} params
   *   thumbprint: lowercase hex SHA-1 of the chosen certificate's DER.
   *   hashes: base64 digests to sign.
   *   digestAlgorithm: sha256 (default), sha384 or sha512.
   * @returns {Promise<{signatures: string[]}>} base64 CMS-ready signature
   *   values, same order as the input hashes.
   */
  signHash({ thumbprint, hashes, digestAlgorithm = "sha256" }) {
    return this._call("signHash", { thumbprint, hashes, digestAlgorithm });
  }

  _call(command, params, { timeoutMs, timeoutCode, timeoutMessage } = {}) {
    return new Promise((resolve, reject) => {
      const requestId = crypto.randomUUID();
      let timer = null;
      if (timeoutMs) {
        timer = setTimeout(() => {
          this._pending.delete(requestId);
          reject(new OpenSignerError(timeoutCode || "INTERNAL", timeoutMessage || `No response to "${command}"`));
        }, timeoutMs);
      }
      this._pending.set(requestId, { resolve, reject, timer });
      this._listen();
      window.dispatchEvent(new CustomEvent(REQUEST_EVENT, {
        detail: { requestId, command, params },
      }));
    });
  }

  _listen() {
    if (this._onResponse) return;
    this._onResponse = (event) => {
      const detail = event.detail;
      if (!detail) return;
      const entry = this._pending.get(detail.requestId);
      if (!entry) return; // not ours, or already timed out
      this._pending.delete(detail.requestId);
      if (entry.timer) clearTimeout(entry.timer);
      if (detail.error) {
        entry.reject(new OpenSignerError(detail.error.code || "INTERNAL", detail.error.message));
      } else {
        entry.resolve(detail.result);
      }
    };
    window.addEventListener(RESPONSE_EVENT, this._onResponse);
  }
}

window.OpenSigner = OpenSigner;
window.OpenSignerError = OpenSignerError;
})();
