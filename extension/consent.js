// Consent popup: show the asking origin, report Allow or Deny to the background.

const api = globalThis.browser ?? globalThis.chrome;
const origin = new URLSearchParams(location.search).get("origin") || "";

document.getElementById("origin").textContent = origin;

function decide(allow) {
  Promise.resolve(api.runtime.sendMessage({ type: "org.docsigner.consent", origin, allow }))
    .catch(() => {})
    .finally(() => window.close()); // background also closes us, whichever wins
}

document.getElementById("allow").addEventListener("click", () => decide(true));
document.getElementById("deny").addEventListener("click", () => decide(false));
