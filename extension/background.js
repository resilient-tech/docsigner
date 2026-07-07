// Background service worker (event page on Firefox).
// Routes bridge requests to the native messaging host (CONTRACTS.md sections 2 and 3):
// "ping" is answered here, everything else goes through an origin consent check
// and then to com.opensigner.host.

const api = globalThis.browser ?? globalThis.chrome;

const HOST_NAME = "com.opensigner.host";
const NATIVE_COMMANDS = new Set(["getVersion", "listCertificates", "signHash"]);
const CONSENT_COMMANDS = new Set(["listCertificates", "signHash"]);
const CONSENT_MESSAGE = "org.opensigner.consent";
// ponytail: one flat timeout for every native call. signHash includes a PIN
// prompt, so it has to be generous. Per-command budgets if this ever bites.
const NATIVE_TIMEOUT_MS = 120000;

// One long-lived native messaging port instead of a process per request, so
// the host survives between calls and its in-memory PIN cache works
// (CONTRACTS.md section 2). Chrome 116+ keeps this service worker alive while
// the port is open; if the worker is ever killed anyway, the port drops, the
// host exits, the PIN cache dies with it, and the next request reconnects.
let nativePort = null;
const pendingNative = new Map(); // request id -> {resolve, reject, timer}

function getNativePort() {
  if (nativePort) return nativePort;
  nativePort = api.runtime.connectNative(HOST_NAME);
  nativePort.onMessage.addListener((reply) => {
    const pending = pendingNative.get(reply && reply.id);
    if (!pending) return;
    pendingNative.delete(reply.id);
    clearTimeout(pending.timer);
    pending.resolve(reply);
  });
  nativePort.onDisconnect.addListener(() => {
    const text = String(
      (api.runtime.lastError && api.runtime.lastError.message) || "native host disconnected"
    );
    nativePort = null;
    for (const pending of pendingNative.values()) {
      clearTimeout(pending.timer);
      pending.reject(new Error(text));
    }
    pendingNative.clear();
  });
  return nativePort;
}

function callNative(message) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pendingNative.delete(message.id);
      reject(new Error(
        `Native host did not answer "${message.command}" within ${NATIVE_TIMEOUT_MS / 1000}s`
      ));
    }, NATIVE_TIMEOUT_MS);
    pendingNative.set(message.id, { resolve, reject, timer });
    try {
      getNativePort().postMessage(message);
    } catch (e) {
      pendingNative.delete(message.id);
      clearTimeout(timer);
      reject(e);
    }
  });
}

// Consent prompts waiting for a click, keyed by origin.
// ponytail: in-memory map. The open response channel keeps the worker alive
// long enough for a human to click a button; persist to storage if it doesn't.
const pendingConsent = new Map();

api.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message && message.type === CONSENT_MESSAGE) {
    settleConsent(message.origin, message.allow === true);
    return;
  }
  handleRequest(message, sender).then(sendResponse);
  return true; // keep sendResponse usable after this listener returns
});

api.windows.onRemoved.addListener((windowId) => {
  // Consent window closed without a click counts as deny, but isn't remembered.
  for (const [origin, pending] of pendingConsent) {
    if (pending.windowId === windowId) {
      pendingConsent.delete(origin);
      pending.resolve({ allowed: false, remember: false });
    }
  }
});

async function handleRequest(message, sender) {
  try {
    const command = message && message.command;
    const params = (message && message.params) || {};

    if (command === "ping") {
      return { result: { installed: true, version: api.runtime.getManifest().version } };
    }
    if (!NATIVE_COMMANDS.has(command)) {
      return errorReply("UNSUPPORTED", `Unknown command "${command}"`);
    }

    if (CONSENT_COMMANDS.has(command)) {
      const origin = senderOrigin(sender);
      if (!origin) {
        return errorReply("ORIGIN_DENIED", "Request origin could not be determined");
      }
      if (!(await originAllowed(origin))) {
        return errorReply("ORIGIN_DENIED", `The user denied ${origin} access to certificates`);
      }
    }

    const id = message.requestId || crypto.randomUUID();
    const reply = await callNative({ id, command, params });
    if (reply && reply.error) {
      return { error: { code: reply.error.code || "INTERNAL", message: reply.error.message || "" } };
    }
    return { result: (reply && reply.result) || {} };
  } catch (e) {
    const text = String((e && e.message) || e);
    if (/native messaging host not found|no such native application|not installed/i.test(text)) {
      return errorReply("HOST_NOT_INSTALLED", "The OpenSigner native host is not installed");
    }
    return errorReply("INTERNAL", text);
  }
}

function errorReply(code, message) {
  return { error: { code, message } };
}

function senderOrigin(sender) {
  if (sender.origin && sender.origin !== "null") return sender.origin;
  try {
    return new URL(sender.url).origin;
  } catch {
    return null;
  }
}

// ---- origin consent ----

async function originAllowed(origin) {
  const stored = await api.storage.local.get("origins");
  const origins = stored.origins || {};
  if (origin in origins) return origins[origin];

  const { allowed, remember } = await askConsent(origin);
  if (remember) {
    origins[origin] = allowed;
    await api.storage.local.set({ origins });
  }
  return allowed;
}

function askConsent(origin) {
  const existing = pendingConsent.get(origin);
  if (existing) return existing.promise; // one prompt per origin at a time

  const pending = { windowId: null };
  pending.promise = new Promise((resolve) => {
    pending.resolve = resolve;
  });
  pendingConsent.set(origin, pending);

  const url = api.runtime.getURL("consent.html") + "?origin=" + encodeURIComponent(origin);
  api.windows.create({ url, type: "popup", width: 400, height: 240 }).then(
    (win) => { pending.windowId = win.id; },
    () => {
      pendingConsent.delete(origin);
      pending.resolve({ allowed: false, remember: false });
    }
  );
  return pending.promise;
}

function settleConsent(origin, allow) {
  const pending = pendingConsent.get(origin);
  if (!pending) return;
  pendingConsent.delete(origin);
  pending.resolve({ allowed: allow, remember: true });
  if (pending.windowId !== null) {
    api.windows.remove(pending.windowId).catch(() => {});
  }
}
