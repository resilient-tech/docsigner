// The only part of the extension allowed to talk to the host binary.
// "ping" it answers itself. Everything else asks the user for permission first.

const api = globalThis.browser ?? globalThis.chrome;

const HOST_NAME = "com.docsigner.host";
// Where someone missing the host goes to get it. Only the extension can tell
// the host is absent, so the link rides on the HOST_NOT_INSTALLED error and the
// page renders it. We do not open a tab ourselves: the page asked for a
// signature, so the page owns what the user sees next.
const HOST_DOWNLOAD_URL = "https://docsigner.pages.dev/download#web";
// checkUpdate is here and not in CONSENT_COMMANDS on purpose: like getVersion it
// reveals nothing about the user, only which host version is installed. It does
// make the host fetch one fixed URL, but a page cannot choose that URL, so the
// worst a hostile page achieves is a request it could have made itself.
const NATIVE_COMMANDS = new Set([
  "getVersion",
  "checkUpdate",
  "listCertificates",
  "signHash",
]);
const CONSENT_COMMANDS = new Set(["listCertificates", "signHash"]);
const CONSENT_MESSAGE = "org.docsigner.consent";
// ponytail: one flat timeout for every call. Signing waits on a human typing a
// PIN, so it has to be generous. Per-command budgets if this ever bites.
const NATIVE_TIMEOUT_MS = 120000;

// One long-lived connection, not a process per call, so the host stays up and
// remembers the PIN between calls. If we ever get killed, the host exits, the
// remembered PIN dies with it, and the next call reconnects. That is fine.
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
      (api.runtime.lastError && api.runtime.lastError.message) ||
        "native host disconnected",
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
      reject(
        new Error(
          `Native host did not answer "${message.command}" within ${NATIVE_TIMEOUT_MS / 1000}s`,
        ),
      );
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

// Permission prompts waiting on a click, one per site.
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
  // Closed without answering means no, but we do not remember it as one.
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
      return {
        result: { installed: true, version: api.runtime.getManifest().version },
      };
    }
    if (!NATIVE_COMMANDS.has(command)) {
      return errorReply("UNSUPPORTED", `Unknown command "${command}"`);
    }

    let origin = null;
    if (CONSENT_COMMANDS.has(command)) {
      origin = senderOrigin(sender);
      if (!origin) {
        return errorReply(
          "ORIGIN_DENIED",
          "Request origin could not be determined",
        );
      }
      if (!(await originAllowed(origin))) {
        return errorReply(
          "ORIGIN_DENIED",
          `The user denied ${origin} access to certificates`,
        );
      }
    }

    const id = message.requestId || crypto.randomUUID();
    // Shown in the PIN dialog. Taken from the browser, never from the page,
    // and it overwrites whatever the page sent. A page allowed to name itself
    // could name someone else.
    const nativeParams = origin ? { ...params, origin } : params;
    const reply = await callNative({ id, command, params: nativeParams });
    if (reply && reply.error) {
      return {
        error: {
          code: reply.error.code || "INTERNAL",
          message: reply.error.message || "",
        },
      };
    }
    return { result: (reply && reply.result) || {} };
  } catch (e) {
    const text = String((e && e.message) || e);
    if (
      /native messaging host not found|no such native application|not installed/i.test(
        text,
      )
    ) {
      return errorReply(
        "HOST_NOT_INSTALLED",
        "The DocSigner native host is not installed",
        HOST_DOWNLOAD_URL,
      );
    }
    return errorReply("INTERNAL", text);
  }
}

function errorReply(code, message, downloadUrl = null) {
  const error = { code, message };
  if (downloadUrl) error.downloadUrl = downloadUrl;
  return { error };
}

function senderOrigin(sender) {
  if (sender.origin && sender.origin !== "null") return sender.origin;
  try {
    return new URL(sender.url).origin;
  } catch {
    return null;
  }
}

// ---- asking the user whether a site may see their certificates ----

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

  const url =
    api.runtime.getURL("consent.html") +
    "?origin=" +
    encodeURIComponent(origin);
  // 280, not the old 240. Measured at this width: the page is 231 px tall once
  // the update banner shows, 203 without, and Allow/Deny end at 211. This is the
  // OUTER height, so a title bar takes 30-40 of it — at 240 the buttons landed
  // right on the edge and would have clipped on Windows. Sized up front rather
  // than resized when the banner arrives: a popup that grows under the cursor is
  // worse than a little empty space below the buttons.
  api.windows.create({ url, type: "popup", width: 400, height: 280 }).then(
    (win) => {
      pending.windowId = win.id;
    },
    () => {
      pendingConsent.delete(origin);
      pending.resolve({ allowed: false, remember: false });
    },
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
