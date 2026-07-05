"""signer-core: PDF digital signing on top of pyHanko.

Interrupted signing sessions for hardware tokens, one-shot server-side
signing, PAdES baseline profiles, and signature validation.
"""

from .errors import SignerError
from .profiles import Profile
from .server_signer import sign_with_p12
from .session import SessionState, SigningSession
from .trust import build_validation_context, load_trust_certs, make_timestamper
from .validation import validate

__all__ = [
    "Profile",
    "SessionState",
    "SignerError",
    "SigningSession",
    "build_validation_context",
    "load_trust_certs",
    "make_timestamper",
    "sign_with_p12",
    "validate",
]
