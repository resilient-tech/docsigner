// What a web page uses to reach a USB token.
// Talks to the browser extension and nothing else. No dependencies.

const REQUEST_EVENT = "org.docsigner.request";
const RESPONSE_EVENT = "org.docsigner.response";

/**
 * What every failed call throws. Switch on `code`; the list is in CONTRACTS.md.
 */
export class DocSignerError extends Error {
  constructor(code, message) {
    super(message || code);
    this.name = "DocSignerError";
    this.code = code;
  }
}

export class DocSigner {
  constructor() {
    this._pending = new Map(); // requestId -> {resolve, reject, timer}
    this._onResponse = null;
  }

  /**
   * Is the extension there and answering?
   * @param {{timeout?: number}} [options] how long to wait, default 2000 ms.
   * @returns {Promise<{installed: boolean, version: string}>}
   */
  init({ timeout = 2000 } = {}) {
    return this._call("ping", {}, {
      timeoutMs: timeout,
      timeoutCode: "EXTENSION_NOT_INSTALLED",
      timeoutMessage: `The DocSigner extension did not answer within ${timeout} ms. It is probably not installed.`,
    });
  }

  /**
   * Every certificate on every plugged-in token.
   * @returns {Promise<{certificates: Array<object>, readers?: Array<object>}>}
   *   `readers` and `diagnostics` explain an empty list: nothing plugged in,
   *   or plugged in with no driver. Field names are in CONTRACTS.md.
   */
  async listCertificates() {
    const result = await this._call("listCertificates", {});
    return {
      certificates: result.certificates || [],
      readers: result.readers || [],
      diagnostics: result.diagnostics || null,
    };
  }

  /**
   * Sign hashes with the token. Everything in one call costs one PIN prompt.
   * @param {{thumbprint: string, hashes: string[], digestAlgorithm?: string, pin?: string}} params
   *   `thumbprint` picks the certificate, `hashes` are base64.
   *   Pass `pin` and the host skips its own dialog, which makes the PIN your
   *   page's problem to protect.
   * @returns {Promise<{signatures: string[]}>} in the same order as the hashes.
   */
  signHash({ thumbprint, hashes, digestAlgorithm = "sha256", pin }) {
    const params = { thumbprint, hashes, digestAlgorithm };
    if (pin) params.pin = pin;
    return this._call("signHash", params);
  }

  _call(command, params, { timeoutMs, timeoutCode, timeoutMessage } = {}) {
    return new Promise((resolve, reject) => {
      const requestId = crypto.randomUUID();
      let timer = null;
      if (timeoutMs) {
        timer = setTimeout(() => {
          this._pending.delete(requestId);
          reject(new DocSignerError(timeoutCode || "INTERNAL", timeoutMessage || `No response to "${command}"`));
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
        entry.reject(new DocSignerError(detail.error.code || "INTERNAL", detail.error.message));
      } else {
        entry.resolve(detail.result);
      }
    };
    window.addEventListener(RESPONSE_EVENT, this._onResponse);
  }
}
