import sys
from pathlib import Path

import pytest

# Make signer_host importable without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signer_host import pkcs11_ops  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_pin_cache():
    """The PIN cache is process-wide state; keep tests independent of order."""
    pkcs11_ops.clear_pin_cache()
    yield
    pkcs11_ops.clear_pin_cache()
