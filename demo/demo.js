// The demo, and the worked example. Copy signDocument() below into your app.

import { DocSigner, DocSignerError } from "../js/docsigner.js";

// Point these at your published extension listing and host installers.
const INSTALL_EXTENSION_URL = "#";
const INSTALL_HOST_URL = "#";

// A plain sentence for every error code. This is the whole list.
const MESSAGES = {
  EXTENSION_NOT_INSTALLED: {
    text: "The DocSigner browser extension is not installed.",
    link: INSTALL_EXTENSION_URL, linkText: "Install the extension",
  },
  HOST_NOT_INSTALLED: {
    text: "The DocSigner native host is not installed on this computer.",
    link: INSTALL_HOST_URL, linkText: "Download the installer",
  },
  ORIGIN_DENIED: { text: "You denied this site access to your certificates. Remove the decision in the extension settings to be asked again." },
  USER_CANCELLED: { text: "Signing was cancelled at the PIN prompt." },
  PIN_INCORRECT: { text: "Wrong PIN. Careful: tokens lock after a few wrong tries." },
  PIN_LOCKED: { text: "The token PIN is locked. Unlock it with your token vendor's tool before signing." },
  TOKEN_NOT_FOUND: { text: "No token found. Plug in your USB token or smartcard and list certificates again." },
  CERT_NOT_FOUND: { text: "The selected certificate is no longer available. List certificates again." },
  MODULE_ERROR: { text: "The token driver reported an error. Unplug and replug the token, then retry." },
  UNSUPPORTED: { text: "This operation is not supported by the installed host version." },
  DOCUMENT_INVALID: { text: "The server could not read this file (wrong format for the chosen signature type?)." },
  CERT_INVALID: { text: "The server rejected the selected certificate." },
  SESSION_NOT_FOUND: { text: "The signing session was not found on the server. Start again." },
  SESSION_EXPIRED: { text: "The signing session expired (they last 15 minutes). Start again." },
  SIGNATURE_INVALID: { text: "The server rejected the signature produced by the token." },
  PROFILE_UNSUPPORTED: { text: "The server is missing configuration for this profile. B-T needs TSA_URL; B-LT and B-LTA also need TRUST_DIR." },
  INTERNAL: { text: "Something went wrong." },
};

const el = (id) => document.getElementById(id);
const signer = new DocSigner();
let certificates = [];

// What each document type needs from the form.
const DOCTYPE_UI = {
  pdf: {
    accept: "application/pdf,.pdf",
    hint: "The signature lands inside the PDF. Pick a profile below.",
    needsCert: true, profiles: "all",
  },
  cades: {
    accept: "",
    hint: "Any file type; the result is a detached .p7s signed by your token. Profiles: B-B or B-T.",
    needsCert: true, profiles: "bt",
  },
  xades: {
    accept: ".xml,text/xml,application/xml",
    hint: "Signed on the server with its P12 key (set P12_PATH); the token and extension stay out of this path.",
    needsCert: false, profiles: "none",
  },
};

el("list").addEventListener("click", listCertificates);
el("sign").addEventListener("click", signDocument);
el("doctype").addEventListener("change", applyDoctype);
el("method").addEventListener("change", applyDoctype);
el("visible").addEventListener("change", () => {
  el("visible-controls").style.display = el("visible").checked ? "" : "none";
});
el("verify").addEventListener("click", verifyDocument);
applyDoctype();

// PIN lives until the tab closes, and no longer. Think hard before you keep
// one anywhere else.
el("pin").value = sessionStorage.getItem("docsigner-pin") || "";
el("pin").addEventListener("input", () => {
  sessionStorage.setItem("docsigner-pin", el("pin").value);
});

function applyDoctype() {
  const kind = el("doctype").value;
  const ui = DOCTYPE_UI[kind];
  const serverKey = kind === "xades" || (kind === "pdf" && el("method").value === "server");
  el("file").setAttribute("accept", ui.accept);
  el("file").multiple = kind === "pdf"; // several PDFs = bulk signing, one PIN
  el("doctype-hint").textContent = ui.hint
    + (kind === "pdf" ? " Select several files to bulk-sign them with one PIN." : "");
  el("method").disabled = kind !== "pdf"; // CAdES is token-only, XAdES server-only
  if (kind !== "pdf") el("method").value = kind === "xades" ? "server" : "token";
  el("cert-fieldset").style.opacity = ui.needsCert && !serverKey ? "" : "0.45";
  for (const option of el("profile").options) {
    const isBt = option.value === "B-B" || option.value === "B-T";
    option.disabled = ui.profiles === "bt" ? !isBt : false;
  }
  if (ui.profiles === "bt" && !["B-B", "B-T"].includes(el("profile").value)) {
    el("profile").value = "B-T";
  }
  el("profile").disabled = ui.profiles === "none";
  el("visible").disabled = kind !== "pdf";
  el("sign").disabled = ui.needsCert && !serverKey && certificates.length === 0;
}

async function listCertificates() {
  el("list").disabled = true;
  setStatus("info", "Looking for certificates...");
  try {
    await signer.init({ timeout: 2000 });
    const listed = await signer.listCertificates();
    certificates = listed.certificates;
    renderCertificates();
    if (certificates.length === 0) {
      const reader = (listed.readers || [])[0];
      if (reader && reader.driverFound === false) {
        setStatus("error", `Reader "${reader.name}" detected but its PKCS#11 driver is missing.`);
      } else if (listed.diagnostics && listed.diagnostics.hostWillRestart) {
        setStatus("error", `Reader "${reader ? reader.name : "token"}" detected but nothing could be read. The token connection has been reset — list again.`);
      } else if (reader) {
        setStatus("error", `Reader "${reader.name}" detected but no certificate could be read. Replug the token.`);
      } else {
        setStatus("error", "No certificates found. Is your token plugged in?");
      }
    } else {
      setStatus("info", `Found ${certificates.length} certificate(s).`);
      el("sign").disabled = false;
    }
  } catch (e) {
    showError(e);
  } finally {
    el("list").disabled = false;
  }
}

function renderCertificates() {
  const select = el("cert");
  select.innerHTML = "";
  // A token often holds three certificates. Put the ones that can sign on top.
  const canSign = (cert) =>
    !!(cert.keyUsage && (cert.keyUsage.digitalSignature || cert.keyUsage.nonRepudiation));
  certificates
    .map((cert, i) => ({ cert, i }))
    .sort((a, b) => canSign(b.cert) - canSign(a.cert))
    .forEach(({ cert, i }) => {
      const option = document.createElement("option");
      const until = (cert.validTo || "").slice(0, 10);
      const tag = canSign(cert) ? "signing, " : "";
      option.value = i;
      option.textContent = `${commonName(cert.subject)} (${tag}${cert.tokenLabel || "token"}, valid until ${until})`;
      select.appendChild(option);
    });
  select.disabled = certificates.length === 0;
}

function commonName(subject) {
  const match = /CN=([^,]+)/.exec(subject || "");
  return match ? match[1] : subject || "Unknown signer";
}

// The Options box, turned into what the server expects.
async function buildOptions(kind) {
  const options = { profile: el("profile").value };
  if (el("tsa").value) options.tsa = el("tsa").value;
  if (el("digest").value !== "sha256") options.digest_algorithm = el("digest").value;
  if (el("reason").value.trim()) options.reason = el("reason").value.trim();
  if (el("location").value.trim()) options.location = el("location").value.trim();
  if (kind === "pdf" && el("visible").checked) {
    const appearance = {
      page: Math.max(0, (parseInt(el("sigpage").value, 10) || 1) - 1),
      position: el("sigpos").value, // server computes the box from the real page size
    };
    if (el("sigtext").value.trim()) appearance.text = el("sigtext").value.trim();
    const logo = el("siglogo").files[0];
    if (logo) appearance.image = await fileToBase64(logo);
    options.appearance = appearance;
  }
  return options;
}

// The whole flow. With a token: start, sign the hash, complete. Many PDFs
// share one PIN. With a server key: one call, done.
async function signDocument() {
  const kind = el("doctype").value;
  const files = Array.from(el("file").files);
  if (!files.length) return setStatus("error", "Choose a file first.");
  const serverKey = el("method").value === "server" || kind === "xades";
  const cert = certificates[el("cert").value];
  if (!serverKey && !cert) {
    return setStatus("error", "List certificates and pick one first.");
  }

  el("sign").disabled = true;
  try {
    const options = await buildOptions(kind);

    if (kind === "xades") {
      setStatus("info", "Signing on the server...");
      const done = await post("/api/xades/sign-server-side", {
        document: await fileToBase64(files[0]), options: {},
      });
      return setStatus("success", "Signed. ", [{
        href: serverUrl() + done.download_url, text: "Download the signed XML",
      }]);
    }

    if (kind === "pdf" && serverKey) {
      const links = [];
      for (const [i, file] of files.entries()) {
        setStatus("info", `Signing on the server (${i + 1}/${files.length})...`);
        const done = await post("/api/sign-server-side", {
          document: await fileToBase64(file), options,
        });
        links.push({ href: serverUrl() + done.download_url, text: `Download ${file.name} (signed)` });
      }
      return setStatus("success", `Signed ${links.length} document(s). `, links);
    }

    if (kind === "pdf" && files.length > 1) return bulkSign(files, cert, options);

    const base = kind === "cades" ? "/api/cades" : "/api";
    setStatus("info", "Uploading document and preparing the signature...");
    const session = await post(`${base}/signatures`, {
      document: await fileToBase64(files[0]),
      certificate: cert.certificate,
      options,
    });
    const pdfaNote = session.pdfa_note ? `\n${session.pdfa_note}` : "";

    const pin = el("pin").value;
    setStatus("info", (pin ? "Waiting for the token..."
                           : "Waiting for the token. Enter your PIN in the prompt...") + pdfaNote);
    const { signatures } = await signer.signHash({
      thumbprint: cert.thumbprint,
      hashes: [session.to_sign_hash],
      digestAlgorithm: session.digest_algorithm,
      pin,
    });

    setStatus("info", "Embedding the signature...");
    const done = await post(`${base}/signatures/${session.session_id}/complete`, {
      signature: signatures[0],
    });

    const url = serverUrl() + done.download_url;
    const label = kind === "cades" ? "Download the .p7s signature" : "Download the signed PDF";
    setStatus("success", `Signed.${pdfaNote} `, [{ href: url, text: label }]);
  } catch (e) {
    showError(e);
  } finally {
    el("sign").disabled = false;
  }
}

// Many PDFs, one PIN.
async function bulkSign(files, cert, options) {
  setStatus("info", `Uploading ${files.length} documents...`);
  const documents = [];
  for (const file of files) documents.push(await fileToBase64(file));
  const batch = await post("/api/signatures/batch", {
    documents, certificate: cert.certificate, options,
  });

  const pin = el("pin").value;
  setStatus("info", pin ? "Signing all hashes on the token..."
                        : `Signing ${files.length} hashes — one PIN prompt for the whole batch...`);
  const { signatures } = await signer.signHash({
    thumbprint: cert.thumbprint,
    hashes: batch.sessions.map((s) => s.to_sign_hash),
    digestAlgorithm: batch.digest_algorithm,
    pin,
  });

  setStatus("info", "Embedding the signatures...");
  const done = await post("/api/signatures/batch-complete", {
    items: batch.sessions.map((s, i) => ({ session_id: s.session_id, signature: signatures[i] })),
  });

  const links = done.documents.map((doc, i) => ({
    href: serverUrl() + doc.download_url, text: `Download ${files[i].name} (signed)`,
  }));
  setStatus("success", `Signed ${links.length} documents with one PIN. `, links);
}

// Verify panel: /api/validate rendered as one card per signature.
async function verifyDocument() {
  const file = el("verify-file").files[0];
  if (!file) return setStatus("error", "Choose a signed PDF to verify.");
  const box = el("verify-result");
  box.innerHTML = "";
  el("verify").disabled = true;
  try {
    const result = await post("/api/validate", { document: await fileToBase64(file) });
    if (!result.signatures.length) {
      box.appendChild(sigCard("This PDF carries no signatures.", false, ""));
      return;
    }
    for (const sig of result.signatures) {
      // "intact" is about the signed bytes. "modifications_ok" is about what
      // came after: timestamps fine, content edits not.
      const altered = sig.modifications_ok === false;
      const ok = sig.valid && sig.intact && !altered;
      const headline = `${ok ? "✓" : "✗"} ${sig.field_name} — ${sig.signer || "unknown signer"}`;
      const integrity = !sig.intact ? "signed content MODIFIED"
        : altered ? "signed content intact, but the document was ALTERED after signing"
        : "intact";
      const meta = [
        sig.signing_time ? `Signed: ${sig.signing_time}` : null,
        `Integrity: ${integrity}`,
        `Trust: ${sig.trusted ? "chains to a trusted CA" : "not trusted by this server's TRUST_DIR"}`,
        sig.profile_notes || null,
      ].filter(Boolean).join("\n");
      box.appendChild(sigCard(headline, ok, meta));
    }
    if (result.pdfa) {
      box.appendChild(sigCard(`PDF/A-${result.pdfa.part}${result.pdfa.conformance || ""} document`, true, ""));
    }
  } catch (e) {
    showError(e);
  } finally {
    el("verify").disabled = false;
  }
}

function sigCard(headline, ok, meta) {
  const card = document.createElement("div");
  card.className = "sig-card";
  const head = document.createElement("div");
  head.className = ok ? "ok" : "bad";
  head.textContent = headline;
  card.appendChild(head);
  if (meta) {
    const details = document.createElement("div");
    details.className = "meta";
    details.textContent = meta;
    card.appendChild(details);
  }
  return card;
}

// ---- helpers ----

function serverUrl() {
  return el("server").value.trim().replace(/\/+$/, "");
}

async function post(path, body) {
  let response;
  try {
    response = await fetch(serverUrl() + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new DocSignerError("INTERNAL", `Could not reach the server at ${serverUrl()}. Is signer-server running?`);
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = (data && data.error) || { code: "INTERNAL", message: `Server answered HTTP ${response.status}` };
    throw new DocSignerError(error.code, error.message);
  }
  return data;
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(",", 2)[1]); // strip the data: prefix
    reader.onerror = () => reject(new DocSignerError("INTERNAL", "Could not read the chosen file"));
    reader.readAsDataURL(file);
  });
}

function showError(e) {
  const code = e instanceof DocSignerError ? e.code : "INTERNAL";
  const known = MESSAGES[code] || MESSAGES.INTERNAL;
  const detail = known === MESSAGES.INTERNAL && e.message ? ` (${e.message})` : "";
  setStatus("error", `${known.text}${detail}`, known.link ? { href: known.link, text: known.linkText } : null);
  console.error(e);
}

function setStatus(kind, text, links = null) {
  const status = el("status");
  status.className = kind;
  status.textContent = text;
  for (const link of [].concat(links || [])) {
    if (!link || !link.href) continue;
    const a = document.createElement("a");
    a.href = link.href;
    a.textContent = link.text || link.href;
    if (link.href.startsWith("http")) a.target = "_blank";
    status.appendChild(a);
  }
}
