//! Turn a raw certificate into the fields the caller wants.
//!
//! Used by both backends, tokens and the OS store, so neither has to reach
//! into the other.

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

/// The hash algorithms we accept. `parse` is the gate; this list lets a test
/// walk them all.
#[cfg(test)]
pub const DIGEST_ALGORITHMS: [&str; 3] = ["sha256", "sha384", "sha512"];

/// How each part of a certificate's name is spelled out.
///
/// This string goes in the certificate picker, in front of a human, so the
/// spellings are pinned rather than pretty. The first block is the short forms
/// everyone knows, the second the long ones. Indian DSCs really do carry
/// `telephone_number`, so the second block is a live path.
///
/// Anything in neither shows up as a dotted number, which is the standard
/// answer for an attribute nobody recognises.
const NAME_SHORT: [(&str, &str); 25] = [
    // The short forms.
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
    // The long forms, for everything the short table misses.
    ("2.5.4.20", "telephone_number"),
    ("1.2.840.113549.1.9.2", "unstructured_name"),
    ("1.2.840.113549.1.9.8", "unstructured_address"),
    ("2.5.4.41", "name"),
    ("2.5.4.15", "business_category"),
    ("2.5.4.16", "postal_address"),
    ("2.5.4.43", "initials"),
    ("2.5.4.44", "generation_qualifier"),
    ("2.5.4.46", "dn_qualifier"),
    ("2.5.4.13", "description"),
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

    /// How long the hash is. Used to cut an EC signature in half.
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

/// The short fingerprint every command uses to name a certificate.
pub fn thumbprint(der: &[u8]) -> String {
    let digest = Sha1::digest(der);
    let mut out = String::with_capacity(40);
    for byte in digest {
        use std::fmt::Write;
        let _ = write!(out, "{byte:02x}");
    }
    out
}

/// One certificate, unpacked. Whoever found it fills in where it came from.
pub fn cert_info(
    der: &[u8],
    token_label: &str,
    module_name: &str,
    source: Source,
) -> Result<CertInfo> {
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

/// The certificate's name as one line, most specific part first.
///
/// Built by hand rather than using the library's own formatting, which escapes
/// things and hex-encodes anything it does not know. A human reads this.
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

/// Read one piece of text out of a certificate. Indian DSCs use three
/// different encodings in the wild, so handle all of them.
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
        // Two bytes per character. Decoding the pairs by hand is shorter than
        // going through the library's own type.
        Tag::BmpString => utf16be_to_string(value.value()),
        // Anything else: show what we can. Never fail a whole scan over one
        // strange field.
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
        other => Err(HostError::unsupported(format!(
            "unsupported key type: {other}"
        ))),
    }
}

/// What this key is allowed to do. All false if the certificate does not say.
pub fn key_usage(cert: &Certificate) -> KeyUsageFlags {
    let usage = cert
        .tbs_certificate
        .get::<KeyUsage>()
        .ok()
        .flatten()
        .map(|(_, u)| u);
    let has =
        |flag: x509_cert::ext::pkix::KeyUsages| usage.as_ref().is_some_and(|u| u.0.contains(flag));
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

/// Can this one sign? The OS store also holds encryption and login
/// certificates, and offering those would only confuse the picker.
pub fn signing_capable(der: &[u8]) -> bool {
    let Ok(cert) = parse(der) else { return false };
    match cert.tbs_certificate.get::<KeyUsage>() {
        Ok(Some((_, usage))) => {
            use x509_cert::ext::pkix::KeyUsages as U;
            usage.0.contains(U::DigitalSignature) || usage.0.contains(U::NonRepudiation)
        }
        // Says nothing about what it can do, so assume it can sign.
        Ok(None) => true,
        Err(_) => false,
    }
}

/// The envelope an RSA signature expects around a hash.
///
/// Built out in the open rather than pasted as a magic hex string, so it can be
/// read. A test pins it against the bytes everyone else uses.
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

/// Repackage an EC signature.
///
/// Both the token and Windows hand back two numbers glued together. The
/// signature format wants them wrapped properly.
pub fn ecdsa_raw_to_der(raw: &[u8]) -> Result<Vec<u8>> {
    if raw.is_empty() || raw.len() % 2 != 0 {
        return Err(HostError::internal(format!(
            "malformed raw ECDSA signature ({} bytes)",
            raw.len()
        )));
    }
    let half = raw.len() / 2;
    // This applies the fiddly number rules for us: strip leading zeros, and add
    // one back when the value would otherwise read as negative.
    let r =
        UintRef::new(&raw[..half]).map_err(|e| HostError::internal(format!("bad ECDSA r: {e}")))?;
    let s =
        UintRef::new(&raw[half..]).map_err(|e| HostError::internal(format!("bad ECDSA s: {e}")))?;

    let mut body = Vec::new();
    r.encode_to_vec(&mut body)
        .map_err(|e| HostError::internal(format!("cannot encode ECDSA r: {e}")))?;
    s.encode_to_vec(&mut body)
        .map_err(|e| HostError::internal(format!("cannot encode ECDSA s: {e}")))?;
    Ok(der_sequence(&body))
}

/// Put a header on the front of some already-encoded bytes.
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

    /// The exact bytes every other RSA implementation agrees on. Drift from
    /// these and our signatures stop verifying everywhere, so pin them.
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
