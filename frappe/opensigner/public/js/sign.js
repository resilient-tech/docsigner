// OpenSigner desk UI: the "Digitally Sign" form button, the certificate
// dialog, and the bulk list action. Every server call lands in opensigner.api;
// every signature comes from the OpenSigner extension (opensigner.iife.js).
(() => {
	const LAST_CERT_KEY = "opensigner:last_cert";
	const boot = () => (frappe.boot && frappe.boot.opensigner) || { doctypes: [] };

	// ---- form button --------------------------------------------------------

	$(document).on("form-refresh", (event, frm) => {
		if (!frm || frm.is_new() || !boot().doctypes.includes(frm.doctype)) return;
		frappe.call({
			method: "opensigner.api.get_sign_context",
			args: { doctype: frm.doctype, name: frm.doc.name },
			callback: (r) => r.message && render_form_ui(frm, r.message),
		});
	});

	function render_form_ui(frm, ctx) {
		if (ctx.last_log) {
			const log = ctx.last_log;
			const verify = log.verification_url
				? ` &middot; <a href="${log.verification_url}" target="_blank">${__("Verify")}</a>`
				: "";
			frm.dashboard.set_headline(
				`${frappe.utils.icon("check", "sm")} ${__("Digitally signed by {0} on {1}", [
					frappe.utils.escape_html(log.certificate_subject || log.signer),
					frappe.datetime.str_to_user(log.creation),
				])} &middot; <a href="${log.signed_file}" target="_blank">${__("Signed PDF")}</a>${verify}`
			);
		}
		const signable = ctx.print_formats.filter((pf) => pf.can_sign);
		if (!signable.length) return;
		frm.add_custom_button(ctx.last_log ? __("Digitally Sign Again") : __("Digitally Sign"), () =>
			pick_print_format(signable, (pf) => {
				if (pf.mode === "Server Key (automatic)") {
					server_sign(frm, pf);
				} else {
					token_sign_single(frm, pf, ctx);
				}
			})
		);
	}

	function pick_print_format(print_formats, then) {
		if (print_formats.length === 1) return then(print_formats[0]);
		const d = new frappe.ui.Dialog({
			title: __("Sign which print format?"),
			fields: [{
				fieldname: "pf", fieldtype: "Select", label: __("Print Format"),
				options: print_formats.map((pf) => pf.print_format).join("\n"), reqd: 1,
			}],
			primary_action_label: __("Continue"),
			primary_action(values) {
				d.hide();
				then(print_formats.find((pf) => pf.print_format === values.pf));
			},
		});
		d.show();
	}

	function server_sign(frm, pf) {
		frappe.confirm(
			__("Sign {0} with the server-held key ({1})?", [frm.doc.name, pf.print_format]),
			() => frappe.call({
				method: "opensigner.api.sign_now",
				args: { doctype: frm.doctype, name: frm.doc.name, print_format: pf.print_format },
				freeze: true,
				freeze_message: __("Signing on the server…"),
				callback: (r) => signed_toast(r.message, () => frm.reload_doc()),
			})
		);
	}

	async function token_sign_single(frm, pf, ctx) {
		const picked = await pick_certificate(ctx);
		if (!picked) return;
		const { signer, cert } = picked;
		try {
			const started = await frappe.xcall("opensigner.api.start", {
				doctype: frm.doctype, name: frm.doc.name,
				print_format: pf.print_format, certificate: cert.certificate,
			});
			frappe.dom.freeze(__("Confirm the PIN prompt from your token…"));
			const { signatures } = await signer.signHash({
				thumbprint: cert.thumbprint,
				hashes: [started.to_sign_hash],
				digestAlgorithm: started.digest_algorithm,
			});
			frappe.dom.freeze(__("Embedding the signature…"));
			const result = await frappe.xcall("opensigner.api.complete", {
				session_id: started.session_id, signature: signatures[0],
			});
			remember_cert(cert);
			frappe.dom.unfreeze();
			signed_toast(result, () => frm.reload_doc());
		} catch (err) {
			frappe.dom.unfreeze();
			show_signing_error(err);
		}
	}

	function signed_toast(result, after) {
		if (!result) return;
		const verify = result.verification_url
			? `<br><a href="${result.verification_url}" target="_blank">${__("Verification page")}</a>`
			: "";
		frappe.msgprint({
			title: __("Digitally Signed"),
			indicator: "green",
			message: `<a href="${result.file_url}" target="_blank">${result.file_name}</a>${verify}`,
		});
		after && after();
	}

	// ---- certificate dialog --------------------------------------------------

	async function pick_certificate(ctx) {
		if (!window.OpenSigner) {
			frappe.msgprint(__("The OpenSigner browser library did not load; run bench build and refresh."));
			return null;
		}
		const signer = new OpenSigner();
		try {
			await signer.init({ timeout: 2500 });
		} catch (err) {
			show_signing_error(err);
			return null;
		}

		let listed;
		try {
			listed = await signer.listCertificates();
		} catch (err) {
			show_signing_error(err);
			return null;
		}
		const certs = listed.certificates || listed || [];
		if (!certs.length) {
			const reader_hint = (listed.readers || []).some((r) => r.driverFound === false)
				? __("A token is plugged in but its PKCS#11 driver is missing — install the vendor driver.")
				: __("Plug in your DSC token and try again.");
			frappe.msgprint({ title: __("No certificates found"), indicator: "orange", message: reader_hint });
			return null;
		}

		return new Promise((resolve) => {
			const remembered = localStorage.getItem(LAST_CERT_KEY);
			let selected = certs.find((c) => c.thumbprint === remembered) || certs[0];
			const d = new frappe.ui.Dialog({
				title: __("Sign with certificate"),
				fields: [{ fieldname: "list", fieldtype: "HTML" }],
				primary_action_label: __("Sign"),
				primary_action() {
					d.hide();
					resolve({ signer, cert: selected });
				},
				secondary_action_label: __("Cancel"),
				secondary_action: () => { d.hide(); resolve(null); },
			});
			const body = $(d.fields_dict.list.wrapper);
			const preview = (cert) => {
				let name = cn_of(cert.subject) || cert.subject;
				if (ctx.handwritten.capitalize) {
					name = name.split(" ").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
				}
				return `<div class="opensigner-preview ${ctx.handwritten.bold ? "bold" : ""}">${frappe.utils.escape_html(name)}</div>`;
			};
			const render = () => {
				body.html(`
					${certs.map((cert) => `
						<div class="opensigner-cert ${cert === selected ? "selected" : ""}" data-thumb="${cert.thumbprint}">
							<div class="opensigner-cert-subject">${frappe.utils.escape_html(cn_of(cert.subject) || cert.subject)}</div>
							<div class="opensigner-cert-meta">
								${frappe.utils.escape_html(cn_of(cert.issuer) || cert.issuer)}
								&middot; ${__("valid till {0}", [frappe.datetime.str_to_user(cert.validTo)])}
								&middot; ${frappe.utils.escape_html(cert.tokenLabel || "")}
							</div>
						</div>`).join("")}
					<div class="opensigner-preview-label">${__("Stamp preview")}</div>
					${preview(selected)}`);
				body.find(".opensigner-cert").on("click", function () {
					selected = certs.find((c) => c.thumbprint === $(this).data("thumb"));
					render();
				});
			};
			render();
			d.show();
		});
	}

	function cn_of(dn) {
		const match = /(?:^|[,/])\s*CN=([^,/]+)/.exec(dn || "");
		return match ? match[1].trim() : null;
	}

	function remember_cert(cert) {
		localStorage.setItem(LAST_CERT_KEY, cert.thumbprint);
	}

	function show_signing_error(err) {
		const code = err && err.code;
		if (code === "USER_CANCELLED") return; // the user knows; stay quiet
		const friendly = {
			EXTENSION_NOT_INSTALLED: __("The OpenSigner browser extension is not installed (or is disabled). Install it, then reload this page."),
			HOST_NOT_INSTALLED: __("The OpenSigner native host is not installed on this computer. Run the host installer, then reload."),
			ORIGIN_DENIED: __("You declined certificate access for this site. Click the OpenSigner extension icon to allow it."),
			TOKEN_NOT_FOUND: __("No DSC token detected — plug it in and try again."),
			CERT_NOT_FOUND: __("The chosen certificate is no longer on the token."),
			PIN_INCORRECT: __("Wrong PIN. Careful — tokens lock after repeated wrong PINs."),
			PIN_LOCKED: __("The token PIN is locked. Unlock it with your token vendor's utility before signing."),
			MODULE_ERROR: __("The token driver (PKCS#11 module) failed. Reconnect the token or reinstall the driver."),
		};
		frappe.msgprint({
			title: __("Signing failed"),
			indicator: "red",
			message: friendly[code] || (err && (err.message || err._server_messages)) || String(err),
		});
	}

	// ---- bulk list action ----------------------------------------------------

	boot().doctypes.forEach((doctype) => {
		const settings = frappe.listview_settings[doctype] || (frappe.listview_settings[doctype] = {});
		const previous_onload = settings.onload;
		settings.onload = function (listview) {
			previous_onload && previous_onload.call(this, listview);
			listview.page.add_actions_menu_item(__("Digitally Sign"), () => bulk_sign(listview), true);
		};
	});

	async function bulk_sign(listview) {
		const names = listview.get_checked_items(true);
		if (!names.length) return;
		if (names.length > 50) {
			frappe.msgprint(__("Batch signing is capped at 50 documents; {0} are selected.", [names.length]));
			return;
		}
		const print_formats = await frappe.db.get_list("Print Format", {
			filters: { doc_type: listview.doctype, opensigner_enabled: 1 },
			fields: ["name", "opensigner_mode"],
		});
		if (!print_formats.length) return;
		pick_print_format(
			print_formats.map((pf) => ({ print_format: pf.name, mode: pf.opensigner_mode })),
			(pf) => (pf.mode === "Server Key (automatic)"
				? bulk_server_sign(listview, names, pf)
				: bulk_token_sign(listview, names, pf))
		);
	}

	function bulk_server_sign(listview, names, pf) {
		frappe.confirm(
			__("Sign {0} documents with the server-held key?", [names.length]),
			async () => {
				for (let i = 0; i < names.length; i++) {
					frappe.show_progress(__("Signing"), i + 1, names.length, names[i]);
					await frappe.xcall("opensigner.api.sign_now", {
						doctype: listview.doctype, name: names[i], print_format: pf.print_format,
					});
				}
				frappe.hide_progress();
				frappe.msgprint({ title: __("Digitally Signed"), indicator: "green",
					message: __("{0} documents signed.", [names.length]) });
				listview.refresh();
			}
		);
	}

	async function bulk_token_sign(listview, names, pf) {
		const ctx = { handwritten: { capitalize: true, bold: false } };
		const picked = await pick_certificate(ctx);
		if (!picked) return;
		const { signer, cert } = picked;
		try {
			frappe.dom.freeze(__("Preparing {0} documents…", [names.length]));
			const started = await frappe.xcall("opensigner.api.start_batch", {
				items: names.map((name) => ({
					doctype: listview.doctype, name, print_format: pf.print_format,
				})),
				certificate: cert.certificate,
			});
			frappe.dom.freeze(__("Confirm the PIN prompt — one PIN signs all {0} documents…", [names.length]));
			const { signatures } = await signer.signHash({
				thumbprint: cert.thumbprint,
				hashes: started.sessions.map((s) => s.to_sign_hash),
				digestAlgorithm: started.digest_algorithm,
			});
			frappe.dom.freeze(__("Embedding signatures…"));
			const done = await frappe.xcall("opensigner.api.complete_batch", {
				items: started.sessions.map((s, i) => ({
					session_id: s.session_id, signature: signatures[i], name: s.name,
				})),
			});
			remember_cert(cert);
			frappe.dom.unfreeze();
			frappe.msgprint({ title: __("Digitally Signed"), indicator: "green",
				message: __("{0} documents signed with one PIN.", [done.documents.length]) });
			listview.refresh();
		} catch (err) {
			frappe.dom.unfreeze();
			show_signing_error(err);
			listview.refresh(); // earlier documents in a failed batch stay signed
		}
	}
})();
