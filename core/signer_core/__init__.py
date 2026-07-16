"""signer-core: PDF digital signing on top of pyHanko.

Interrupted signing sessions for hardware tokens, one-shot server-side
signing, PAdES baseline profiles, and signature validation.
"""

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
