//! Chrome native messaging framing: 4-byte little-endian length prefix + UTF-8 JSON.

use std::io::{self, Read, Write};

/// Chrome's own cap on a single message. A corrupt length prefix would
/// otherwise have us allocate whatever 4 bytes of garbage asked for.
const MAX_FRAME_BYTES: u32 = 64 * 1024 * 1024;

/// Read one framed payload.
///
/// `Ok(None)` is a clean EOF at a frame boundary. An EOF inside a frame is an
/// error, the same distinction framing.py draws.
pub fn read_frame(stream: &mut impl Read) -> io::Result<Option<Vec<u8>>> {
    let mut header = [0u8; 4];
    match read_exact_or_eof(stream, &mut header)? {
        0 => return Ok(None),
        4 => {}
        _ => {
            return Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                "stream ended inside a frame header",
            ))
        }
    }
    let length = u32::from_le_bytes(header);
    if length > MAX_FRAME_BYTES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!("frame of {length} bytes exceeds the {MAX_FRAME_BYTES}-byte limit"),
        ));
    }
    let mut payload = vec![0u8; length as usize];
    let read = read_exact_or_eof(stream, &mut payload)?;
    if read < payload.len() {
        return Err(io::Error::new(
            io::ErrorKind::UnexpectedEof,
            "stream ended inside a frame payload",
        ));
    }
    Ok(Some(payload))
}

/// Write one framed payload and flush.
pub fn write_frame(stream: &mut impl Write, payload: &[u8]) -> io::Result<()> {
    let length = u32::try_from(payload.len())
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "frame is larger than 4 GiB"))?;
    stream.write_all(&length.to_le_bytes())?;
    stream.write_all(payload)?;
    stream.flush()
}

/// Serialize and write one JSON message as a frame.
pub fn write_message(stream: &mut impl Write, value: &impl serde::Serialize) -> io::Result<()> {
    let payload = serde_json::to_vec(value)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
    write_frame(stream, &payload)
}

/// Fill `buffer`, looping over short reads. Returns how many bytes landed;
/// less than `buffer.len()` means the stream ended.
fn read_exact_or_eof(stream: &mut impl Read, buffer: &mut [u8]) -> io::Result<usize> {
    let mut filled = 0;
    while filled < buffer.len() {
        match stream.read(&mut buffer[filled..]) {
            Ok(0) => break,
            Ok(n) => filled += n,
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        }
    }
    Ok(filled)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trips_a_frame() {
        let mut buffer = Vec::new();
        write_frame(&mut buffer, br#"{"id":"1"}"#).unwrap();
        assert_eq!(&buffer[..4], &10u32.to_le_bytes());
        let mut cursor = io::Cursor::new(buffer);
        assert_eq!(read_frame(&mut cursor).unwrap().unwrap(), br#"{"id":"1"}"#);
    }

    #[test]
    fn clean_eof_at_a_boundary_is_none() {
        let mut cursor = io::Cursor::new(Vec::new());
        assert!(read_frame(&mut cursor).unwrap().is_none());
    }

    #[test]
    fn eof_inside_a_header_is_an_error() {
        let mut cursor = io::Cursor::new(vec![1u8, 0]);
        assert!(read_frame(&mut cursor).is_err());
    }

    #[test]
    fn eof_inside_a_payload_is_an_error() {
        let mut framed = 8u32.to_le_bytes().to_vec();
        framed.extend_from_slice(b"abc");
        let mut cursor = io::Cursor::new(framed);
        assert!(read_frame(&mut cursor).is_err());
    }

    #[test]
    fn refuses_an_absurd_length_prefix() {
        let mut cursor = io::Cursor::new(u32::MAX.to_le_bytes().to_vec());
        assert!(read_frame(&mut cursor).is_err());
    }

    #[test]
    fn reads_two_frames_back_to_back() {
        let mut buffer = Vec::new();
        write_frame(&mut buffer, b"one").unwrap();
        write_frame(&mut buffer, b"two").unwrap();
        let mut cursor = io::Cursor::new(buffer);
        assert_eq!(read_frame(&mut cursor).unwrap().unwrap(), b"one");
        assert_eq!(read_frame(&mut cursor).unwrap().unwrap(), b"two");
        assert!(read_frame(&mut cursor).unwrap().is_none());
    }
}
