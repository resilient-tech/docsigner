"""pkcs11_ops tests against a fake PKCS#11 stack backed by real keys.

The fake token holds a certificate and a private key built with cryptography.
Its sign() applies textbook PKCS#1 v1.5 padding to whatever bytes the host
hands it (the DigestInfo), so if the host's wrapping is wrong, verification
against the public key fails. For EC the fake signs with cryptography and
returns raw r||s, exercising the host's DER conversion.
"""

import base64
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509 as cx509
from cryptography.hazmat.primitives import hashes as chashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import (
    Prehashed,
    decode_dss_signature,
)
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID
from pkcs11 import Attribute, Mechanism, ObjectClass
from pkcs11 import exceptions as p11ex

from signer_host import modules, pkcs11_ops
from signer_host.errors import HostError


# --- helpers: real keys and certs ---

def make_cert(private_key, common_name):
    # Conventional DER order: least specific first, CN last. The host renders
    # names reversed (RFC 4514), so CN comes first in the output.
    name = cx509.Name([
        cx509.NameAttribute(NameOID.COUNTRY_NAME, "IN"),
        cx509.NameAttribute(NameOID.ORGANIZATION_NAME, "OpenSigner Tests"),
        cx509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cert = (
        cx509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(private_key.public_key())
        .serial_number(cx509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(private_key, chashes.SHA256())
    )
    return cert.public_bytes(Encoding.DER)


def raw_pkcs1_sign(private_key, data):
    """Textbook RSA over an EMSA-PKCS1-v1_5 padded block, no hashing, no DigestInfo."""
    numbers = private_key.private_numbers()
    n = numbers.public_numbers.n
    k = (n.bit_length() + 7) // 8
    padded = b"\x00\x01" + b"\xff" * (k - len(data) - 3) + b"\x00" + data
    signature = pow(int.from_bytes(padded, "big"), numbers.d, n)
    return signature.to_bytes(k, "big")


# --- the fake PKCS#11 stack ---

class FakeObject:
    def __init__(self, attrs, signer=None):
        self.attrs = attrs
        self._signer = signer

    def __getitem__(self, attribute):
        return self.attrs[attribute]

    def sign(self, data, mechanism=None):
        return self._signer(data, mechanism)


class FakeSession:
    def __init__(self, token):
        self._token = token

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_objects(self, attrs=None):
        for obj in self._token.objects:
            if all(obj.attrs.get(key) == value for key, value in (attrs or {}).items()):
                yield obj


class FakeToken:
    def __init__(self, objects, label="FakeToken", expected_pin="1234", login_error=None):
        self.objects = objects
        self.label = label
        self.expected_pin = expected_pin
        self.login_error = login_error
        self.logins = 0

    def open(self, rw=False, user_pin=None):
        if user_pin is not None:
            if self.login_error is not None:
                raise self.login_error
            if user_pin != self.expected_pin:
                raise p11ex.PinIncorrect()
            self.logins += 1
        return FakeSession(self)


class FakeSlot:
    """One slot; get_token() raises when the slot is empty or broken,
    which is exactly what ProxKey's driver does for its unused readers."""

    def __init__(self, token=None, error=None, slot_id=0):
        self._token = token
        self._error = error
        self.slot_id = slot_id

    def get_token(self):
        if self._error is not None:
            raise self._error
        return self._token


class FakeLib:
    """Mirrors the python-pkcs11 surface the host uses: slots, not get_tokens().

    Deliberately has no get_tokens() so a regression back to the aborting
    whole-scan call fails these tests immediately.
    """

    def __init__(self, tokens=None, slots=None):
        if slots is None:
            slots = [FakeSlot(token, slot_id=i) for i, token in enumerate(tokens or [])]
        self.slots = slots

    def get_slots(self, token_present=False):
        return list(self.slots)


def rsa_token(private_key, der, label="RSA Token"):
    cka_id = b"\x01"

    def signer(data, mechanism):
        assert mechanism == Mechanism.RSA_PKCS
        return raw_pkcs1_sign(private_key, data)

    cert = FakeObject({Attribute.CLASS: ObjectClass.CERTIFICATE, Attribute.VALUE: der,
                       Attribute.ID: cka_id, Attribute.LABEL: "rsa-cert"})
    key = FakeObject({Attribute.CLASS: ObjectClass.PRIVATE_KEY, Attribute.ID: cka_id,
                      Attribute.LABEL: "rsa-cert"}, signer=signer)
    return FakeToken([cert, key], label=label)


def ec_token(private_key, der, label="EC Token"):
    cka_id = b"\x02"
    size = (private_key.curve.key_size + 7) // 8

    def signer(data, mechanism):
        assert mechanism == Mechanism.ECDSA
        der_sig = private_key.sign(data, ec.ECDSA(Prehashed(chashes.SHA256())))
        r, s = decode_dss_signature(der_sig)
        return r.to_bytes(size, "big") + s.to_bytes(size, "big")

    cert = FakeObject({Attribute.CLASS: ObjectClass.CERTIFICATE, Attribute.VALUE: der,
                       Attribute.ID: cka_id, Attribute.LABEL: "ec-cert"})
    key = FakeObject({Attribute.CLASS: ObjectClass.PRIVATE_KEY, Attribute.ID: cka_id,
                      Attribute.LABEL: "ec-cert"}, signer=signer)
    return FakeToken([cert, key], label=label)


@pytest.fixture
def fake_env(monkeypatch):
    """Install fake tokens behind a fake module path. Returns the installer."""
    def install(tokens, module_path="/fake/pkcs11.so"):
        lib = FakeLib(tokens)
        monkeypatch.setattr(modules, "discover_modules", lambda: [module_path])
        monkeypatch.setattr(pkcs11_ops, "load_library", lambda path: lib)
        return lib
    return install


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def ec_key():
    return ec.generate_private_key(ec.SECP256R1())


# --- listCertificates ---

def test_list_certificates_contract_fields(fake_env, rsa_key):
    der = make_cert(rsa_key, "John Doe")
    fake_env([rsa_token(rsa_key, der)])
    certs = pkcs11_ops.list_certificates()
    assert len(certs) == 1
    cert = certs[0]
    assert cert["thumbprint"] == hashlib.sha1(der).hexdigest()
    assert base64.b64decode(cert["certificate"]) == der
    assert cert["subject"].startswith("CN=John Doe")
    assert "O=OpenSigner Tests" in cert["subject"]
    assert cert["issuer"] == cert["subject"]
    assert cert["keyType"] == "RSA"
    assert cert["tokenLabel"] == "RSA Token"
    assert cert["moduleName"] == "pkcs11.so"
    for field in ("validFrom", "validTo"):
        assert cert[field].endswith("Z") and "T" in cert[field]
        datetime.strptime(cert[field], "%Y-%m-%dT%H:%M:%SZ")


def test_list_certificates_reports_ec_key_type(fake_env, ec_key):
    der = make_cert(ec_key, "EC Holder")
    fake_env([ec_token(ec_key, der)])
    certs = pkcs11_ops.list_certificates()
    assert certs[0]["keyType"] == "EC"


def test_load_library_reinitializes_each_scan(monkeypatch):
    """A long-lived host must re-enumerate slots per scan, or a replug/sleep
    leaves its cached handle blind. reinitialize() is best effort: a driver
    that refuses it still yields a usable (already-loaded) module."""
    class RecordingLib:
        def __init__(self, fail): self.calls = 0; self.fail = fail
        def reinitialize(self):
            self.calls += 1
            if self.fail:
                raise RuntimeError("driver refuses reinitialize")

    good = RecordingLib(fail=False)
    monkeypatch.setattr(pkcs11_ops.pkcs11, "lib", lambda path: good)
    assert pkcs11_ops.load_library("/fake.so") is good and good.calls == 1

    bad = RecordingLib(fail=True)
    monkeypatch.setattr(pkcs11_ops.pkcs11, "lib", lambda path: bad)
    assert pkcs11_ops.load_library("/fake.so") is bad  # swallowed, still usable


def test_list_certificates_survives_broken_module(monkeypatch):
    monkeypatch.setattr(modules, "discover_modules", lambda: ["/fake/broken.so"])

    def broken(path):
        raise RuntimeError("dlopen failed")

    monkeypatch.setattr(pkcs11_ops, "load_library", broken)
    assert pkcs11_ops.list_certificates() == []


# --- signHash: RSA ---

def test_rsa_signature_verifies_as_pkcs1_v15(fake_env, rsa_key):
    der = make_cert(rsa_key, "RSA Signer")
    fake_env([rsa_token(rsa_key, der)])
    digest = hashlib.sha256(b"document to sign").digest()

    signatures = pkcs11_ops.sign_hashes(
        hashlib.sha1(der).hexdigest(), [digest], "sha256",
        pin_provider=lambda label: "1234",
    )

    # The fake only padded and exponentiated; a passing verify proves the
    # host produced the exact DigestInfo PKCS#1 v1.5 expects.
    rsa_key.public_key().verify(
        signatures[0], digest, padding.PKCS1v15(), Prehashed(chashes.SHA256())
    )


def test_batch_signs_all_hashes_with_one_login(fake_env, rsa_key):
    der = make_cert(rsa_key, "Batch Signer")
    token = rsa_token(rsa_key, der)
    fake_env([token])
    digests = [hashlib.sha256(bytes([i])).digest() for i in range(3)]
    pin_calls = []

    signatures = pkcs11_ops.sign_hashes(
        hashlib.sha1(der).hexdigest(), digests, "sha256",
        pin_provider=lambda label: pin_calls.append(label) or "1234",
    )

    assert len(signatures) == 3
    assert token.logins == 1
    assert pin_calls == [token.label]
    for signature, digest in zip(signatures, digests):
        rsa_key.public_key().verify(
            signature, digest, padding.PKCS1v15(), Prehashed(chashes.SHA256())
        )


# --- signHash: EC ---

def test_ec_signature_verifies_after_der_conversion(fake_env, ec_key):
    der = make_cert(ec_key, "EC Signer")
    fake_env([ec_token(ec_key, der)])
    digest = hashlib.sha256(b"ec document").digest()

    signatures = pkcs11_ops.sign_hashes(
        hashlib.sha1(der).hexdigest(), [digest], "sha256",
        pin_provider=lambda label: "1234",
    )

    ec_key.public_key().verify(
        signatures[0], digest, ec.ECDSA(Prehashed(chashes.SHA256()))
    )


def test_ecdsa_raw_to_der_round_trip(ec_key):
    digest = hashlib.sha256(b"round trip").digest()
    der_sig = ec_key.sign(digest, ec.ECDSA(Prehashed(chashes.SHA256())))
    r, s = decode_dss_signature(der_sig)
    raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    assert pkcs11_ops.ecdsa_raw_to_der(raw) == der_sig


def test_ecdsa_raw_to_der_rejects_odd_length():
    with pytest.raises(HostError) as err:
        pkcs11_ops.ecdsa_raw_to_der(b"\x01\x02\x03")
    assert err.value.code == "INTERNAL"


# --- error mapping ---

def sign_call(thumbprint, pin="1234"):
    digest = hashlib.sha256(b"x").digest()
    return pkcs11_ops.sign_hashes(thumbprint, [digest], "sha256",
                                  pin_provider=lambda label: pin)


def test_wrong_pin_maps_to_pin_incorrect(fake_env, rsa_key):
    der = make_cert(rsa_key, "Pin Test")
    fake_env([rsa_token(rsa_key, der)])
    with pytest.raises(HostError) as err:
        sign_call(hashlib.sha1(der).hexdigest(), pin="wrong")
    assert err.value.code == "PIN_INCORRECT"


def test_locked_pin_maps_to_pin_locked(fake_env, rsa_key):
    der = make_cert(rsa_key, "Locked Test")
    token = rsa_token(rsa_key, der)
    token.login_error = p11ex.PinLocked()
    fake_env([token])
    with pytest.raises(HostError) as err:
        sign_call(hashlib.sha1(der).hexdigest())
    assert err.value.code == "PIN_LOCKED"


def test_token_removed_at_login_maps_to_token_not_found(fake_env, rsa_key):
    der = make_cert(rsa_key, "Removed Test")
    token = rsa_token(rsa_key, der)
    token.login_error = p11ex.TokenNotPresent()
    fake_env([token])
    with pytest.raises(HostError) as err:
        sign_call(hashlib.sha1(der).hexdigest())
    assert err.value.code == "TOKEN_NOT_FOUND"


def test_no_token_present_maps_to_token_not_found(fake_env):
    fake_env([])
    with pytest.raises(HostError) as err:
        sign_call("ab" * 20)
    assert err.value.code == "TOKEN_NOT_FOUND"


def test_unknown_thumbprint_maps_to_cert_not_found(fake_env, rsa_key):
    der = make_cert(rsa_key, "Present Cert")
    fake_env([rsa_token(rsa_key, der)])
    with pytest.raises(HostError) as err:
        sign_call("00" * 20)
    assert err.value.code == "CERT_NOT_FOUND"


def test_module_load_failure_maps_to_module_error(monkeypatch):
    monkeypatch.setattr(modules, "discover_modules", lambda: ["/fake/broken.so"])

    def broken(path):
        raise RuntimeError("dlopen failed")

    monkeypatch.setattr(pkcs11_ops, "load_library", broken)
    with pytest.raises(HostError) as err:
        sign_call("ab" * 20)
    assert err.value.code == "MODULE_ERROR"


def test_unsupported_digest_algorithm(fake_env, rsa_key):
    der = make_cert(rsa_key, "Alg Test")
    fake_env([rsa_token(rsa_key, der)])
    with pytest.raises(HostError) as err:
        pkcs11_ops.sign_hashes(hashlib.sha1(der).hexdigest(),
                               [hashlib.md5(b"x").digest()], "md5",
                               pin_provider=lambda label: "1234")
    assert err.value.code == "UNSUPPORTED"


def test_cancelled_pin_maps_to_user_cancelled(fake_env, rsa_key):
    der = make_cert(rsa_key, "Cancel Test")
    fake_env([rsa_token(rsa_key, der)])

    def cancel(label):
        raise HostError("USER_CANCELLED", "PIN entry was cancelled")

    digest = hashlib.sha256(b"x").digest()
    with pytest.raises(HostError) as err:
        pkcs11_ops.sign_hashes(hashlib.sha1(der).hexdigest(), [digest], "sha256",
                               pin_provider=cancel)
    assert err.value.code == "USER_CANCELLED"


def test_bad_slot_does_not_hide_good_token(monkeypatch, rsa_key):
    """Regression: ProxKey exposes empty reader slots that raise on access.
    One bad slot must never mask a token sitting in another slot."""
    der = make_cert(rsa_key, "ProxKey User")
    lib = FakeLib(slots=[
        FakeSlot(error=p11ex.DeviceRemoved(), slot_id=0),
        FakeSlot(rsa_token(rsa_key, der, label="WD PROXKey"), slot_id=1),
        FakeSlot(error=p11ex.TokenNotPresent(), slot_id=2),
    ])
    monkeypatch.setattr(modules, "discover_modules", lambda: ["/fake/wd.dylib"])
    monkeypatch.setattr(pkcs11_ops, "load_library", lambda path: lib)

    certs = pkcs11_ops.list_certificates()
    assert len(certs) == 1
    assert certs[0]["tokenLabel"] == "WD PROXKey"

    digest = hashlib.sha256(b"payload").digest()
    signatures = pkcs11_ops.sign_hashes(
        certs[0]["thumbprint"], [digest], "sha256", pin_provider=lambda label: "1234"
    )
    assert len(signatures) == 1


def test_duplicate_cert_across_modules_deduplicated(monkeypatch, rsa_key):
    """The same token reachable through two drivers must list its certs once."""
    der = make_cert(rsa_key, "Dup Holder")
    libs = {
        "/fake/a.so": FakeLib([rsa_token(rsa_key, der)]),
        "/fake/b.so": FakeLib([rsa_token(rsa_key, der)]),
    }
    monkeypatch.setattr(modules, "discover_modules", lambda: list(libs))
    monkeypatch.setattr(pkcs11_ops, "load_library", lambda path: libs[path])
    assert len(pkcs11_ops.list_certificates()) == 1


def test_key_usage_reported_for_signing_cert(fake_env, rsa_key):
    """Multi-cert tokens need keyUsage so UIs can pick the signing certificate."""
    name = cx509.Name([cx509.NameAttribute(NameOID.COMMON_NAME, "Usage Holder")])
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cert = (
        cx509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(rsa_key.public_key())
        .serial_number(cx509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(cx509.KeyUsage(
            digital_signature=True, content_commitment=True,
            key_encipherment=False, data_encipherment=False,
            key_agreement=False, key_cert_sign=False, crl_sign=False,
            encipher_only=False, decipher_only=False), critical=True)
        .sign(rsa_key, chashes.SHA256())
    )
    der = cert.public_bytes(Encoding.DER)
    fake_env([rsa_token(rsa_key, der)])
    usage = pkcs11_ops.list_certificates()[0]["keyUsage"]
    assert usage["digitalSignature"] is True
    assert usage["nonRepudiation"] is True  # content_commitment is its new name
    assert usage["keyEncipherment"] is False


def test_key_usage_all_false_when_extension_absent(fake_env, rsa_key):
    der = make_cert(rsa_key, "No Usage Ext")
    fake_env([rsa_token(rsa_key, der)])
    usage = pkcs11_ops.list_certificates()[0]["keyUsage"]
    assert set(usage) == {"digitalSignature", "nonRepudiation", "keyEncipherment",
                          "dataEncipherment", "keyAgreement", "keyCertSign", "crlSign"}
    assert not any(usage.values())


# --- PIN cache ---

def test_pin_cached_across_sign_calls(fake_env, rsa_key):
    der = make_cert(rsa_key, "Cached Signer")
    token = rsa_token(rsa_key, der)
    fake_env([token])
    digest = hashlib.sha256(b"x").digest()
    prompts = []

    def provider(label):
        prompts.append(label)
        return "1234"

    for _ in range(3):
        pkcs11_ops.sign_hashes(hashlib.sha1(der).hexdigest(), [digest], "sha256",
                               pin_provider=provider)

    assert len(prompts) == 1  # first call prompts, the rest hit the cache
    assert token.logins == 3  # every call still logs in with the cached PIN


def test_pin_cache_expires(fake_env, rsa_key, monkeypatch):
    der = make_cert(rsa_key, "Expiring Signer")
    fake_env([rsa_token(rsa_key, der)])
    digest = hashlib.sha256(b"x").digest()
    prompts = []

    def provider(label):
        prompts.append(label)
        return "1234"

    thumb = hashlib.sha1(der).hexdigest()
    pkcs11_ops.sign_hashes(thumb, [digest], "sha256", pin_provider=provider)

    now = pkcs11_ops.time.monotonic()
    monkeypatch.setattr(pkcs11_ops.time, "monotonic",
                        lambda: now + pkcs11_ops.PIN_CACHE_TTL_SECONDS + 1)
    pkcs11_ops.sign_hashes(thumb, [digest], "sha256", pin_provider=provider)

    assert len(prompts) == 2


def test_stale_cached_pin_reprompts_once(fake_env, rsa_key):
    der = make_cert(rsa_key, "Stale Pin Signer")
    token = rsa_token(rsa_key, der)
    fake_env([token])
    digest = hashlib.sha256(b"x").digest()
    thumb = hashlib.sha1(der).hexdigest()

    pkcs11_ops.sign_hashes(thumb, [digest], "sha256", pin_provider=lambda label: "1234")

    token.expected_pin = "5678"  # PIN changed on the token; cache is now stale
    prompts = []

    def provider(label):
        prompts.append(label)
        return "5678"

    signatures = pkcs11_ops.sign_hashes(thumb, [digest], "sha256", pin_provider=provider)
    assert len(signatures) == 1
    assert prompts == ["RSA Token"]  # exactly one fresh prompt, no blind retry


def test_wrong_prompted_pin_not_cached(fake_env, rsa_key):
    der = make_cert(rsa_key, "Wrong Pin Signer")
    fake_env([rsa_token(rsa_key, der)])
    digest = hashlib.sha256(b"x").digest()
    thumb = hashlib.sha1(der).hexdigest()

    with pytest.raises(HostError) as err:
        pkcs11_ops.sign_hashes(thumb, [digest], "sha256", pin_provider=lambda label: "9999")
    assert err.value.code == "PIN_INCORRECT"
    assert pkcs11_ops._cached_pin("RSA Token") is None
