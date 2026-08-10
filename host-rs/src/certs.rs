//! Turn a certificate into the JSON fields CONTRACTS.md section 2 wants.
//!
//! Shared by both signing backends: PKCS#11 tokens (`pkcs11.rs`) and the OS
//! store (`os_store/`). Kept here so neither backend reaches into the other.

use der::asn1::{
    Ia5StringRef, OctetString, PrintableStringRef, TeletexStringRef, UintRef, Utf8StringRef,
};
use der::{Decode, Encode, Sequence, Tag, Tagged};
use serde::Serialize;
use sha1::{Digest, Sha1};
use x509_cert::ext::pkix::KeyUsage;
use x509_cert::name::Name;
use x509_cert::spki::AlgorithmIdentifierOwned;
use x509_cert::Certificate;

use crate::error::{Code, HostError, Result};

pub const DIGEST_ALGORITHMS: [&str; 3] = ["sha256", "sha384", "sha512"];

/// OID -> short name, matching certs.py `_NAME_SHORT` so the rendered subject
/// string is byte-identical to what the Python host produced. Anything absent
/// falls back to the dotted OID, which is what RFC 4514 does.
const NAME_SHORT: [(&str, &str); 15] = [
    ("2.5.4.3", "CN"),
    ("2.5.4.10", "O"),
    ("2.5.4.11", "OU"),
    ("2.5.4.6", "C"),
    ("2.5.4.8", "ST"),
    ("2.5.4.7", "L"),
    ("1.2.840.113549.1.9.1", "E"),
    ("2.5.4.5", "SERIALNUMBER"),
    ("0.9.2342.19200300.100.1.25", "DC"),
    ("2.5.4.12", "T"),
    ("2.5.4.42", "G"),
    ("2.5.4.4", "SN"),
    ("2.5.4.65", "PSEUDONYM"),
    ("2.5.4.9", "STREET"),
    ("2.5.4.17", "POSTALCODE"),
];

const OID_RSA_ENCRYPTION: &str = "1.2.840.113549.1.1.1";
const OID_RSASSA_PSS: &str = "1.2.840.113549.1.1.10";
const OID_EC_PUBLIC_KEY: &str = "1.2.840.10045.2.1";

const OID_SHA256: &str = "2.16.840.1.101.3.4.2.1";
const OID_SHA384: &str = "2.16.840.1.101.3.4.2.2";
const OID_SHA512: &str = "2.16.840.1.101.3.4.2.3";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum KeyType {
    #[serde(rename = "RSA")]
    Rsa,
    #[serde(rename = "EC")]
    Ec,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum Source {
    #[serde(rename = "pkcs11")]
    Pkcs11,
    #[serde(rename = "os-store")]
    OsStore,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DigestAlg {
    Sha256,
    Sha384,
    Sha512,
}

impl DigestAlg {
    pub fn parse(name: &str) -> Result<Self> {
        match name {
            "sha256" => Ok(DigestAlg::Sha256),
            "sha384" => Ok(DigestAlg::Sha384),
            "sha512" => Ok(DigestAlg::Sha512),
            other => Err(HostError::unsupported(format!(
                "unsupported digest algorithm: {other:?}"
            ))),
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            DigestAlg::Sha256 => "sha256",
            DigestAlg::Sha384 => "sha384",
            DigestAlg::Sha512 => "sha512",
        }
    }

    fn oid(self) -> &'static str {
        match self {
            DigestAlg::Sha256 => OID_SHA256,
            DigestAlg::Sha384 => OID_SHA384,
            DigestAlg::Sha512 => OID_SHA512,
        }
    }

    /// Digest length in bytes, used to split a raw r||s ECDSA signature.
    pub fn len(self) -> usize {
        match self {
            DigestAlg::Sha256 => 32,
            DigestAlg::Sha384 => 48,
            DigestAlg::Sha512 => 64,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct KeyUsageFlags {
    #[serde(rename = "digitalSignature")]
    pub digital_signature: bool,
    #[serde(rename = "nonRepudiation")]
    pub non_repudiation: bool,
    #[serde(rename = "keyEncipherment")]
    pub key_encipherment: bool,
    #[serde(rename = "dataEncipherment")]
    pub data_encipherment: bool,
    #[serde(rename = "keyAgreement")]
    pub key_agreement: bool,
    #[serde(rename = "keyCertSign")]
    pub key_cert_sign: bool,
    #[serde(rename = "crlSign")]
    pub crl_sign: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct CertInfo {
    pub thumbprint: String,
    pub certificate: String,
    pub subject: String,
    pub issuer: String,
    #[serde(rename = "validFrom")]
    pub valid_from: String,
    #[serde(rename = "validTo")]
    pub valid_to: String,
    #[serde(rename = "keyType")]
    pub key_type: KeyType,
    #[serde(rename = "keyUsage")]
    pub key_usage: KeyUsageFlags,
    #[serde(rename = "tokenLabel")]
    pub token_label: String,
    #[serde(rename = "moduleName")]
    pub module_name: String,
    pub source: Source,
}

/// SHA-1 of the DER, lowercase hex. The identifier every command keys on.
pub fn thumbprint(der: &[u8]) -> String {
    let digest = Sha1::digest(der);
    let mut out = String::with_capacity(40);
    for byte in digest {
        use std::fmt::Write;
        let _ = write!(out, "{byte:02x}");
    }
    out
}

/// Contract fields for one DER certificate. `token_label`, `module_name` and
/// `source` are filled in by the backend that found it.
pub fn cert_info(der: &[u8], token_label: &str, module_name: &str, source: Source) -> Result<CertInfo> {
    let cert = parse(der)?;
    let tbs = &cert.tbs_certificate;
    Ok(CertInfo {
        thumbprint: thumbprint(der),
        certificate: base64_encode(der),
        subject: name_to_string(&tbs.subject),
        issuer: name_to_string(&tbs.issuer),
        valid_from: iso_utc(&tbs.validity.not_before),
        valid_to: iso_utc(&tbs.validity.not_after),
        key_type: key_type(&cert)?,
        key_usage: key_usage(&cert),
        token_label: token_label.to_string(),
        module_name: module_name.to_string(),
        source,
    })
}

pub fn parse(der: &[u8]) -> Result<Certificate> {
    Certificate::from_der(der)
        .map_err(|e| HostError::internal(format!("certificate is not readable DER: {e}")))
}

/// `CN=..., O=..., C=...`, most specific first.
///
/// Deliberately not `RdnSequence`'s own `Display`: that applies RFC 4514
/// escaping and hex-encodes unknown attributes, neither of which the Python
/// host did, and this string is shown to users in the certificate picker.
pub fn name_to_string(name: &Name) -> String {
    let mut parts = Vec::new();
    for rdn in name.0.iter().rev() {
        for atv in rdn.0.iter() {
            let oid = atv.oid.to_string();
            let key = NAME_SHORT
                .iter()
                .find(|(candidate, _)| *candidate == oid)
                .map(|(_, short)| (*short).to_string())
                .unwrap_or(oid);
            parts.push(format!("{key}={}", attribute_value(&atv.value)));
        }
    }
    parts.join(", ")
}

/// Decode a directory-string attribute value. Indian DSCs turn up with
/// PrintableString, UTF8String and BMPString in the wild.
fn attribute_value(value: &der::Any) -> String {
    match value.tag() {
        Tag::PrintableString => PrintableStringRef::try_from(value)
            .map(|s| s.as_str().to_string())
            .unwrap_or_default(),
        Tag::Utf8String => Utf8StringRef::try_from(value)
            .map(|s| s.as_str().to_string())
            .unwrap_or_default(),
        Tag::Ia5String => Ia5StringRef::try_from(value)
            .map(|s| s.as_str().to_string())
            .unwrap_or_default(),
        Tag::TeletexString => TeletexStringRef::try_from(value)
            .map(|s| s.as_str().to_string())
            .unwrap_or_default(),
        // BMPString is UTF-16BE. der exposes no borrowed ref type for it, and
        // decoding the pairs directly is shorter than round-tripping through
        // an owned BmpString.
        Tag::BmpString => utf16be_to_string(value.value()),
        // Anything else: show the bytes rather than nothing, never fail a scan
        // over one odd attribute.
        _ => String::from_utf8_lossy(value.value()).into_owned(),
    }
}

fn utf16be_to_string(bytes: &[u8]) -> String {
    let units: Vec<u16> = bytes
        .chunks_exact(2)
        .map(|pair| u16::from_be_bytes([pair[0], pair[1]]))
        .collect();
    String::from_utf16_lossy(&units)
}

fn iso_utc(time: &x509_cert::time::Time) -> String {
    let dt = time.to_date_time();
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
        dt.year(),
        dt.month(),
        dt.day(),
        dt.hour(),
        dt.minutes(),
        dt.seconds()
    )
}

fn key_type(cert: &Certificate) -> Result<KeyType> {
    let oid = cert
        .tbs_certificate
        .subject_public_key_info
        .algorithm
        .oid
        .to_string();
    match oid.as_str() {
        OID_RSA_ENCRYPTION | OID_RSASSA_PSS => Ok(KeyType::Rsa),
        OID_EC_PUBLIC_KEY => Ok(KeyType::Ec),
        other => Err(HostError::unsupported(format!("unsupported key type: {other}"))),
    }
}

/// Key-usage booleans; all false when the extension is absent or unreadable,
/// matching certs.py.
pub fn key_usage(cert: &Certificate) -> KeyUsageFlags {
    let usage = cert.tbs_certificate.get::<KeyUsage>().ok().flatten().map(|(_, u)| u);
    let has = |flag: x509_cert::ext::pkix::KeyUsages| {
        usage.as_ref().is_some_and(|u| u.0.contains(flag))
    };
    use x509_cert::ext::pkix::KeyUsages as U;
    KeyUsageFlags {
        digital_signature: has(U::DigitalSignature),
        non_repudiation: has(U::NonRepudiation),
        key_encipherment: has(U::KeyEncipherment),
        data_encipherment: has(U::DataEncipherment),
        key_agreement: has(U::KeyAgreement),
        key_cert_sign: has(U::KeyCertSign),
        crl_sign: has(U::CRLSign),
    }
}

/// Whether a certificate's key usage allows signing, or it carries no key-usage
/// extension at all. The OS store holds encryption and authentication certs
/// too; listing those would only confuse the picker.
pub fn signing_capable(der: &[u8]) -> bool {
    let Ok(cert) = parse(der) else { return false };
    match cert.tbs_certificate.get::<KeyUsage>() {
        Ok(Some((_, usage))) => {
            use x509_cert::ext::pkix::KeyUsages as U;
            usage.0.contains(U::DigitalSignature) || usage.0.contains(U::NonRepudiation)
        }
        // Absent extension: keep it, same as os_store.py.
        Ok(None) => true,
        Err(_) => false,
    }
}

/// PKCS#1 v1.5 DigestInfo: `SEQUENCE { AlgorithmIdentifier, OCTET STRING }`.
///
/// Built rather than pasted as a magic hex prefix so the structure is visible;
/// `digest_info_matches_rfc8017_prefixes` pins it against the known-good bytes.
#[derive(Sequence)]
struct DigestInfo {
    algorithm: AlgorithmIdentifierOwned,
    digest: OctetString,
}

/// Wrap a digest in a DigestInfo for `CKM_RSA_PKCS`.
pub fn digest_info(digest: &[u8], alg: DigestAlg) -> Result<Vec<u8>> {
    if digest.len() != alg.len() {
        return Err(HostError::internal(format!(
            "{} digest must be {} bytes, got {}",
            alg.as_str(),
            alg.len(),
            digest.len()
        )));
    }
    let oid = alg
        .oid()
        .parse()
        .map_err(|_| HostError::internal("bad digest OID"))?;
    let info = DigestInfo {
        algorithm: AlgorithmIdentifierOwned {
            oid,
            // NULL parameters, required by RFC 8017 for these digests.
            parameters: Some(der::Any::null()),
        },
        digest: OctetString::new(digest)
            .map_err(|e| HostError::internal(format!("cannot wrap digest: {e}")))?,
    };
    info.to_der()
        .map_err(|e| HostError::internal(format!("cannot encode DigestInfo: {e}")))
}

/// Raw `r || s` ECDSA signature -> DER `ECDSA-Sig-Value`.
///
/// PKCS#11 `CKM_ECDSA` and Windows CNG both return the raw pair; CMS wants the
/// DER SEQUENCE.
pub fn ecdsa_raw_to_der(raw: &[u8]) -> Result<Vec<u8>> {
    if raw.is_empty() || raw.len() % 2 != 0 {
        return Err(HostError::internal(format!(
            "malformed raw ECDSA signature ({} bytes)",
            raw.len()
        )));
    }
    let half = raw.len() / 2;
    // UintRef applies the DER INTEGER rules for us: leading zeros stripped, one
    // zero byte prepended when the high bit would make the value read negative.
    let r = UintRef::new(&raw[..half])
        .map_err(|e| HostError::internal(format!("bad ECDSA r: {e}")))?;
    let s = UintRef::new(&raw[half..])
        .map_err(|e| HostError::internal(format!("bad ECDSA s: {e}")))?;

    let mut body = Vec::new();
    r.encode_to_vec(&mut body)
        .map_err(|e| HostError::internal(format!("cannot encode ECDSA r: {e}")))?;
    s.encode_to_vec(&mut body)
        .map_err(|e| HostError::internal(format!("cannot encode ECDSA s: {e}")))?;
    Ok(der_sequence(&body))
}

/// Wrap already-encoded DER contents in a SEQUENCE header.
fn der_sequence(contents: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(contents.len() + 4);
    out.push(0x30);
    let len = contents.len();
    if len < 0x80 {
        out.push(len as u8);
    } else if len <= 0xff {
        out.push(0x81);
        out.push(len as u8);
    } else {
        out.push(0x82);
        out.push((len >> 8) as u8);
        out.push((len & 0xff) as u8);
    }
    out.extend_from_slice(contents);
    out
}

pub fn base64_encode(bytes: &[u8]) -> String {
    use base64::Engine;
    base64::engine::general_purpose::STANDARD.encode(bytes)
}

pub fn base64_decode(text: &str) -> Result<Vec<u8>> {
    use base64::Engine;
    base64::engine::general_purpose::STANDARD
        .decode(text)
        .map_err(|_| HostError::new(Code::Internal, "hashes must be valid base64"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn thumbprint_is_lowercase_sha1_hex() {
        // SHA-1 of the empty string.
        assert_eq!(thumbprint(b""), "da39a3ee5e6b4b0d3255bfef95601890afd80709");
        assert_eq!(thumbprint(b"").len(), 40);
    }

    /// The RFC 8017 A.2.4 DigestInfo prefixes every PKCS#1 v1.5 implementation
    /// agrees on. If the built structure ever drifts from these, signatures
    /// stop verifying everywhere, so pin the exact bytes.
    #[test]
    fn digest_info_matches_rfc8017_prefixes() {
        let cases: [(DigestAlg, &[u8]); 3] = [
            (
                DigestAlg::Sha256,
                &[
                    0x30, 0x31, 0x30, 0x0d, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04,
                    0x02, 0x01, 0x05, 0x00, 0x04, 0x20,
                ],
            ),
            (
                DigestAlg::Sha384,
                &[
                    0x30, 0x41, 0x30, 0x0d, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04,
                    0x02, 0x02, 0x05, 0x00, 0x04, 0x30,
                ],
            ),
            (
                DigestAlg::Sha512,
                &[
                    0x30, 0x51, 0x30, 0x0d, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04,
                    0x02, 0x03, 0x05, 0x00, 0x04, 0x40,
                ],
            ),
        ];
        for (alg, prefix) in cases {
            let digest = vec![0xabu8; alg.len()];
            let encoded = digest_info(&digest, alg).unwrap();
            assert_eq!(&encoded[..prefix.len()], prefix, "{}", alg.as_str());
            assert_eq!(&encoded[prefix.len()..], &digest[..], "{}", alg.as_str());
        }
    }

    #[test]
    fn digest_info_rejects_a_wrong_length_digest() {
        assert!(digest_info(&[0u8; 20], DigestAlg::Sha256).is_err());
    }

    #[test]
    fn ecdsa_der_wraps_r_and_s_as_integers() {
        // Both halves have the high bit clear: encoded as-is.
        let raw = [vec![0x01u8; 32], vec![0x02u8; 32]].concat();
        let der = ecdsa_raw_to_der(&raw).unwrap();
        assert_eq!(der[0], 0x30);
        assert_eq!(der[2], 0x02); // INTEGER r
        assert_eq!(der[3], 32);
        assert_eq!(der[2 + 34], 0x02); // INTEGER s
    }

    #[test]
    fn ecdsa_der_pads_a_high_bit_value() {
        // High bit set on both halves: DER must prepend a zero byte so the
        // INTEGER stays positive.
        let raw = [vec![0xffu8; 32], vec![0xffu8; 32]].concat();
        let der = ecdsa_raw_to_der(&raw).unwrap();
        assert_eq!(der[2], 0x02);
        assert_eq!(der[3], 33, "r should be padded to 33 bytes");
        assert_eq!(der[4], 0x00);
    }

    #[test]
    fn ecdsa_der_strips_leading_zeros() {
        let mut r = vec![0x00u8; 32];
        r[31] = 0x07;
        let raw = [r, vec![0x08u8; 32]].concat();
        let der = ecdsa_raw_to_der(&raw).unwrap();
        assert_eq!(der[3], 1, "r should shrink to a single byte");
        assert_eq!(der[4], 0x07);
    }

    #[test]
    fn ecdsa_rejects_an_odd_length() {
        assert!(ecdsa_raw_to_der(&[1, 2, 3]).is_err());
        assert!(ecdsa_raw_to_der(&[]).is_err());
    }

    #[test]
    fn digest_alg_parsing_matches_the_contract() {
        for name in DIGEST_ALGORITHMS {
            assert_eq!(DigestAlg::parse(name).unwrap().as_str(), name);
        }
        assert!(DigestAlg::parse("sha1").is_err());
        assert!(DigestAlg::parse("md5").is_err());
    }
}
