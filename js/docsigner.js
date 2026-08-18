// What a web page uses to reach a USB token.
// Talks to the browser extension and nothing else. No dependencies.

const REQUEST_EVENT = "org.docsigner.request";
const RESPONSE_EVENT = "org.docsigner.response";

// Where someone with no extension goes to get one. A page cannot ask the
// extension for this link when the extension is what's missing, so the answer
// has to be a constant here. Pass `downloadUrl` to the constructor to send
// people to an internal mirror instead.
export const DOWNLOAD_URL = "https://docsigner.pages.dev/download#web";

/**
 * What every failed call throws. Switch on `code`; the list is in CONTRACTS.md.
 * `downloadUrl` is set on the two "not installed" codes: show it as a link.
 */
export class DocSignerError extends Error {
  constructor(code, message, downloadUrl = null) {
    super(message || code);
    this.name = "DocSignerError";
    this.code = code;
    this.downloadUrl = downloadUrl;
  }
}

export class DocSigner {
  constructor({ downloadUrl = DOWNLOAD_URL } = {}) {
    this.downloadUrl = downloadUrl;
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
      timeoutDownloadUrl: this.downloadUrl,
    });
  }

  /**
   * Which of the two pieces are installed, without prompting anyone: `ping` is
   * answered by the extension and `getVersion` names no user data, so neither
   * raises the consent popup or touches the token. Use it to gate a Sign
   * button and to say which piece is missing.
   *
   * Never rejects. A missing piece is a null version.
   * @param {{timeout?: number}} [options] how long to wait for the extension.
   * @returns {Promise<{extension: string|null, host: string|null,
   *   downloadUrl: string|null, error: {code: string, message: string}|null}>}
   *   `downloadUrl` is set when something is missing; `error` explains a host
   *   that answered with something other than a version.
   */
  async status({ timeout = 2000 } = {}) {
    const state = { extension: null, host: null, downloadUrl: null, error: null };
    try {
      state.extension = (await this.init({ timeout })).version;
    } catch (e) {
      state.downloadUrl = e.downloadUrl || this.downloadUrl;
      state.error = { code: e.code, message: e.message };
      return state; // no extension, so nothing can answer for the host either
    }
    try {
      state.host = (await this._call("getVersion", {})).version;
    } catch (e) {
      state.error = { code: e.code, message: e.message };
      // A broken host is not a missing one; only offer the installer for the
      // one code that means absent.
      if (e.code === "HOST_NOT_INSTALLED") state.downloadUrl = e.downloadUrl || this.downloadUrl;
    }
    return state;
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

  /**
   * Ask whether a newer host has been released. Never rejects on a network or
   * feed problem: those come back as `updateAvailable: false` with a `message`,
   * so a check can't break your page.
   *
   * Nobody can push an update to a hand-installed native host, so a stale one
   * stays stale silently. Show `downloadUrl` when `updateAvailable` is true.
   * @returns {Promise<{currentVersion: string, latestVersion: string|null,
   *   updateAvailable: boolean, downloadUrl: string|null, message: string}>}
   */
  checkUpdate() {
    return this._call("checkUpdate", {});
  }

  _call(command, params, { timeoutMs, timeoutCode, timeoutMessage, timeoutDownloadUrl } = {}) {
    return new Promise((resolve, reject) => {
      const requestId = crypto.randomUUID();
      let timer = null;
      if (timeoutMs) {
        timer = setTimeout(() => {
          this._pending.delete(requestId);
          reject(new DocSignerError(
            timeoutCode || "INTERNAL",
            timeoutMessage || `No response to "${command}"`,
            timeoutDownloadUrl || null,
          ));
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
        entry.reject(new DocSignerError(
          detail.error.code || "INTERNAL",
          detail.error.message,
          detail.error.downloadUrl || null,
        ));
      } else {
        entry.resolve(detail.result);
      }
    };
    window.addEventListener(RESPONSE_EVENT, this._onResponse);
  }
}
