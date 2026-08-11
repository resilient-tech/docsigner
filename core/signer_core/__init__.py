"""Turn a PDF into a signed PDF. Sign with a USB token or with a key on disk."""

from .errors import SignerError
from .oneshot import sign_with_p12
from .pdf_sign import SessionState, SigningSession
from .profiles import Profile
from .rendering import page_size, placement_box, render_page
from .trust import build_validation_context, make_timestamper
from .validation import validate

__all__ = [
    "Profile",
    "SessionState",
    "SignerError",
    "SigningSession",
    "build_validation_context",
    "make_timestamper",
    "page_size",
    "placement_box",
    "render_page",
    "sign_with_p12",
    "validate",
]
