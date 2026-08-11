// Page <-> extension bridge (CONTRACTS.md section 3).
// Listens for "org.docsigner.request" CustomEvents on window, forwards them
// to the background, and answers with "org.docsigner.response". Nothing else
// crosses this boundary.

(() => {
  const api = globalThis.browser ?? globalThis.chrome;
  const REQUEST_EVENT = "org.docsigner.request";
  const RESPONSE_EVENT = "org.docsigner.response";

  window.addEventListener(REQUEST_EVENT, (event) => {
    let detail;
    try {
      // JSON round trip: detaches us from page-controlled getters and proxies.
      detail = JSON.parse(JSON.stringify(event.detail));
    } catch {
      return;
    }
    if (!detail || typeof detail.requestId !== "string" || typeof detail.command !== "string") {
      return;
    }

    const { requestId, command, params } = detail;
    Promise.resolve()
      .then(() => api.runtime.sendMessage({ requestId, command, params: params ?? {} }))
      .then((reply) => {
        if (reply && (reply.result !== undefined || reply.error !== undefined)) {
          respond(requestId, reply);
        } else {
          respond(requestId, { error: { code: "INTERNAL", message: "Empty reply from extension background" } });
        }
      })
      .catch((e) => {
        respond(requestId, { error: { code: "INTERNAL", message: String((e && e.message) || e) } });
      });
  });

  function respond(requestId, reply) {
    let detail = { requestId, ...reply };
    if (typeof cloneInto === "function") {
      // Firefox: page code can't read content-script objects unless cloned in.
      detail = cloneInto(detail, window);
    }
    window.dispatchEvent(new CustomEvent(RESPONSE_EVENT, { detail }));
  }
})();
