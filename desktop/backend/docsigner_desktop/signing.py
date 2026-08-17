"""Sign the whole batch.

Two paths, same shape:
- token: get a hash from every file, sign them all on one login, glue them back.
  That is what makes one PIN cover the folder.
- server key: sign each file outright.

Both turn the placement into a box for that page and write <name><suffix>.pdf.
"""

import base64
import logging
from pathlib import Path

from docsigner_core import SigningSession, page_size, placement_box, sign_with_p12

from . import certs, config, store
from .models import AppearanceProfile, Placement, SignRequest

log = logging.getLogger(__name__)


def _box_points(pl: Placement, w_pt: float, h_pt: float) -> list[float]:
    return placement_box(pl.fx, pl.fy, pl.fw, pl.fh, w_pt, h_pt)


def _appearance(profile: AppearanceProfile, box: list[float], page: int,
                reason: str | None, location: str | None) -> dict:
    ap: dict = {"page": page, "box": box}
    if profile.style == "handwritten":
        ap["style"] = "handwritten"
        ap["font"] = profile.font
    elif profile.style == "image":
        ap["style"] = "image"
        if profile.image:
            ap["image"] = profile.image
    lines = []
    if profile.show_name:
        lines.append("Digitally signed by {signer}")
    if profile.show_date:
        lines.append("Date: {ts}")
    if profile.show_reason and reason:
        lines.append("Reason: {reason}")
    if profile.show_location and location:
        lines.append(f"Location: {location}")
    if lines:
        ap["text"] = "\n".join(lines)
    return ap


def _resolve_page(page: int, pages: int) -> int:
    """Keep the page number inside this file. Negative means last page.

    One placement covers the batch, but page 5 of a 6-page file has to land
    somewhere sensible in a 1-page file rather than fail.
    """
    return page if page < 0 else min(page, pages - 1)


def _options(req: SignRequest, box: list[float], page: int) -> dict:
    return {
        "profile": req.standard,
        "reason": req.reason,
        "location": req.location,
        "appearance": _appearance(req.profile, box, page, req.reason, req.location),
    }


def _output_path(path: str, suffix: str) -> Path:
    p = Path(path)
    return p.with_name(f"{p.stem}{suffix}{p.suffix}")


def _skip_reason(path: str, suffix: str) -> str | None:
    """Never overwrite. Skip anything already signed, or already has a signed copy."""
    p = Path(path)
    if suffix and p.stem.endswith(suffix):
        return "already a signed file"
    if _output_path(path, suffix).exists():
        return "signed copy already exists"
    return None


def _err(exc: Exception) -> str:
    return getattr(exc, "message", None) or str(exc)


def outcome(results: list[dict]) -> str:
    """One line for the popup: what actually came out of the run.

    Counted from the written files, not from the signatures the token produced.
    The host used to announce the latter, which is why a run whose timestamp or
    revocation data failed still said it had signed. Wording kept in step with
    notify::signed_message in the host, which says the same thing to a browser.
    """
    signed = sum(1 for r in results if r.get("ok"))
    total = len(results)
    documents = "document" if total == 1 else "documents"
    if signed == total:
        return f"Signed {total} {documents}."
    if signed:
        return f"Signed {signed} of {total} documents."
    return f"Could not sign {total} {documents}."


def sign_files(req: SignRequest) -> list[dict]:
    identity = certs.find_identity(store.KEYS_DIR, req.identity_id)
    if identity is None:
        return [{"path": p, "ok": False, "error": "signing identity not found"} for p in req.files]
    ts, vc = config.context_for(req.standard, req.tsa_url)
    if identity["kind"] == "token":
        results = _sign_token(req, identity, ts, vc)
    else:
        results = _sign_p12(req, identity, ts, vc)
    # Here, not in either branch: the popup is about the run, whichever key signed
    # it, and this is the first point where the answer is known. Imported locally,
    # like every other reference to the host in this package.
    from . import host

    host.notify(outcome(results))
    return results


def _sign_p12(req: SignRequest, identity: dict, ts, vc) -> list[dict]:
    results = []
    for path in req.files:
        reason = _skip_reason(path, req.suffix)
        if reason:
            results.append({"path": path, "ok": False, "skipped": True, "error": reason})
            continue
        try:
            w_pt, h_pt, pages = page_size(path, req.placement.page)
            options = _options(req, _box_points(req.placement, w_pt, h_pt),
                               _resolve_page(req.placement.page, pages))
            signed = sign_with_p12(
                Path(path).read_bytes(), identity["path"], None, options,
                timestamper=ts, validation_context=vc,
            )
            out = _output_path(path, req.suffix)
            out.write_bytes(signed)
            results.append({"path": path, "ok": True, "output": str(out), "name": out.name})
        except Exception as exc:  # noqa: BLE001 - one bad file must not abort the batch
            log.exception("server-key sign failed: %s (standard=%s)", path, req.standard)
            results.append({"path": path, "ok": False, "error": _err(exc)})
    return results


def _sign_token(req: SignRequest, identity: dict, ts, vc) -> list[dict]:
    cert_der = base64.b64decode(identity["certificate"])
    results: dict[str, dict] = {}
    prepared: list[tuple[str, object]] = []
    hashes: list[bytes] = []
    algorithm = "sha256"

    # 1. Get a hash out of every file. Token not needed yet.
    for path in req.files:
        reason = _skip_reason(path, req.suffix)
        if reason:
            results[path] = {"path": path, "ok": False, "skipped": True, "error": reason}
            continue
        try:
            w_pt, h_pt, pages = page_size(path, req.placement.page)
            options = _options(req, _box_points(req.placement, w_pt, h_pt),
                               _resolve_page(req.placement.page, pages))
            state, to_sign, algorithm = SigningSession.start(
                Path(path).read_bytes(), cert_der, options,
                timestamper=ts, validation_context=vc,
            )
            prepared.append((path, state))
            hashes.append(to_sign)
        except Exception as exc:  # noqa: BLE001
            log.exception("prepare failed: %s (standard=%s)", path, req.standard)
            results[path] = {"path": path, "ok": False, "error": _err(exc)}

    # 2. One PIN, every hash signed in one go. Imported late so the server-key
    #    path never loads the token code.
    if hashes:
        try:
            from . import host

            signatures = host.sign_hashes(identity["thumbprint"], hashes, algorithm, req.pin)
        except Exception as exc:  # noqa: BLE001 - batch sign failed for all prepared files
            log.exception("token sign failed (standard=%s)", req.standard)
            # We may be holding a token that has since been unplugged. Forget it.
            certs.invalidate_token_cache()
            for path, _state in prepared:
                results[path] = {"path": path, "ok": False, "error": _err(exc)}
            prepared = []
            signatures = []

        # 3. Glue each signature in and write the file out.
        for (path, state), sig in zip(prepared, signatures):
            try:
                signed = SigningSession.complete(state, sig, timestamper=ts, validation_context=vc)
                out = _output_path(path, req.suffix)
                out.write_bytes(signed)
                results[path] = {"path": path, "ok": True, "output": str(out), "name": out.name}
            except Exception as exc:  # noqa: BLE001
                log.exception("embed failed: %s (standard=%s)", path, req.standard)
                results[path] = {"path": path, "ok": False, "error": _err(exc)}

    return [results[p] for p in req.files if p in results]
