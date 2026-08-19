// The permission popup. Shows who is asking, reports back yes or no.

const api = globalThis.browser ?? globalThis.chrome;
const origin = new URLSearchParams(location.search).get("origin") || "";

document.getElementById("origin").textContent = origin;

function decide(allow) {
  Promise.resolve(
    api.runtime.sendMessage({ type: "org.docsigner.consent", origin, allow }),
  )
    .catch(() => {})
    .finally(() => window.close()); // background also closes us, whichever wins
}

document.getElementById("allow").addEventListener("click", () => decide(true));
document.getElementById("deny").addEventListener("click", () => decide(false));

// A stale host is worth mentioning, and this popup is the one moment the
// extension has someone's attention. Asked for after the buttons already work
// and shown only if there is news, so a slow or dead check never delays the
// decision or leaves an empty strip of colour behind.
//
// Deliberately not a blocker: whether to trust this site has nothing to do with
// whether an update exists, so the banner informs and never gates.
//
// This does start the host and fetch the feed before the user has decided, so a
// prompt that ends in Deny still cost one request. Accepted: it goes to the
// release feed and carries nothing about the user or the asking site, and the
// alternative is checking after the window closes, which nobody would see.
api.runtime
  .sendMessage({ command: "checkUpdate", params: {} })
  .then((reply) => {
    const status = reply && reply.result;
    if (!status || !status.updateAvailable) return;
    showUpdate(status);
  })
  .catch(() => {}); // no host, no network, no news: say nothing

function showUpdate({ latestVersion, downloadUrl }) {
  const banner = document.getElementById("update");
  // textContent, and clipped to a length a version could plausibly be. Both
  // because this string comes from the feed: textContent so markup in it is
  // text, and the clip so a huge one cannot wrap the banner tall enough to
  // push the Deny and Allow buttons out of a fixed-height popup.
  const version = String(latestVersion || "").slice(0, 20);
  banner.textContent = version
    ? `DocSigner ${version} is available. `
    : "A newer DocSigner is available. ";
  // The host drops any downloadUrl that is not https before it reaches us, so
  // this is a link only when there is a safe one to make.
  if (downloadUrl) {
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.target = "_blank";
    link.rel = "noreferrer noopener";
    link.textContent = "Get it";
    banner.appendChild(link);
  }
  banner.classList.add("show");
}
