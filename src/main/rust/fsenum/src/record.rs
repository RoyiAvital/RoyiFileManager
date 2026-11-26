//! FILE_ID_EXTD_DIR_INFO record decoding: the validation of `records()` in
//! core/fs/local/windows/listing.py, which stays the readable reference.

pub const HEADER: usize = 88;
/// The longest name accepted, in bytes: 32,767 UTF-16 units, the longest
/// Windows path (NTFS and ReFS names have at most 255). `Segment` stores a
/// name's length in 15 bits.
pub const MAX_NAME_BYTES: usize = 2 * 32767;
/// 1601-01-01 to 1970-01-01 in 100 ns units.
pub const EPOCH: i64 = 116_444_736_000_000_000;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RecordError {
    Truncated,
    Invalid,
    InvalidOffset,
    InvalidName,
}

impl RecordError {
    pub fn message(self) -> &'static str {
        match self {
            RecordError::Truncated => "Truncated directory record",
            RecordError::Invalid => "Invalid directory record",
            RecordError::InvalidOffset => "Invalid directory record offset",
            RecordError::InvalidName => "Invalid directory entry name",
        }
    }
}

/// One record other than `.` and `..`, borrowed from its batch.
pub struct Record<'a> {
    pub created: i64,
    pub modified: i64,
    pub size: i64,
    pub attributes: u32,
    pub tag: u32,
    pub identity: &'a [u8; 16],
    /// UTF-16LE, an even number of bytes, without `/`, `\` or NUL.
    pub name: &'a [u8],
    /// Every UTF-16 unit is below 256: the name is stored as Latin-1.
    pub latin1: bool,
}

impl Record<'_> {
    #[inline]
    pub fn units(&self) -> impl Iterator<Item = u16> + '_ {
        self.name.chunks_exact(2).map(|pair| u16::from_le_bytes([pair[0], pair[1]]))
    }
}

#[inline]
fn u32_at(header: &[u8; HEADER], offset: usize) -> u32 {
    u32::from_le_bytes(header[offset..offset + 4].try_into().unwrap())
}

#[inline]
fn i64_at(header: &[u8; HEADER], offset: usize) -> i64 {
    i64::from_le_bytes(header[offset..offset + 8].try_into().unwrap())
}

/// Calls `visit` for every record of `data` except `.` and `..`, in order.
/// The first malformed record ends the walk with its error, as `records()` raises.
#[inline]
pub fn for_each<E>(data: &[u8], mut visit: impl FnMut(Record<'_>) -> Result<(), E>) -> Result<(), E>
where
    E: From<RecordError>,
{
    let length = data.len();
    let mut offset = 0usize;
    loop {
        if offset + HEADER > length {
            return Err(RecordError::Truncated.into());
        }
        let header: &[u8; HEADER] = data[offset..offset + HEADER].try_into().unwrap();
        let next = u32_at(header, 0) as usize;
        let size = i64_at(header, 40);
        let name_length = u32_at(header, 60) as usize;
        let end = offset + HEADER + name_length;
        if name_length == 0 || name_length % 2 != 0 || name_length > MAX_NAME_BYTES || end > length || size < 0 {
            return Err(RecordError::Invalid.into());
        }
        if next != 0 && (next % 8 != 0 || next < HEADER + name_length || offset + next + HEADER > length) {
            return Err(RecordError::InvalidOffset.into());
        }
        let name = &data[offset + HEADER..end];
        let dot = name == b".\0" || name == b".\0.\0";
        if !dot {
            // Branchless so the compiler vectorizes it: names are long and many.
            let (mut widest, mut forbidden) = (0u16, false);
            for pair in name.chunks_exact(2) {
                let unit = u16::from_le_bytes([pair[0], pair[1]]);
                widest |= unit;
                forbidden |= (unit == b'/' as u16) | (unit == b'\\' as u16) | (unit == 0);
            }
            if forbidden {
                return Err(RecordError::InvalidName.into());
            }
            visit(Record {
                created: i64_at(header, 8),
                modified: i64_at(header, 24),
                size,
                attributes: u32_at(header, 56),
                tag: u32_at(header, 68),
                identity: header[72..88].try_into().unwrap(),
                name,
                latin1: widest < 256,
            })?;
        }
        if next == 0 {
            return Ok(());
        }
        offset += next;
    }
}

/// (filetime - EPOCH) * 100: Unix nanoseconds, exact for every 64-bit input.
#[inline]
pub fn filetime_ns(filetime: i64) -> i128 {
    (filetime as i128 - EPOCH as i128) * 100
}

#[cfg(test)]
mod tests {
    use super::*;

    pub fn record(name: &str, size: i64, attributes: u32, tag: u32, next: Option<u32>) -> Vec<u8> {
        let units: Vec<u16> = name.encode_utf16().collect();
        let raw: Vec<u8> = units.iter().flat_map(|unit| unit.to_le_bytes()).collect();
        let padded = (HEADER + raw.len()).div_ceil(8) * 8;
        let mut data = vec![0u8; padded];
        data[0..4].copy_from_slice(&next.unwrap_or(padded as u32).to_le_bytes());
        data[40..48].copy_from_slice(&size.to_le_bytes());
        data[56..60].copy_from_slice(&attributes.to_le_bytes());
        data[60..64].copy_from_slice(&(raw.len() as u32).to_le_bytes());
        data[68..72].copy_from_slice(&tag.to_le_bytes());
        data[HEADER..HEADER + raw.len()].copy_from_slice(&raw);
        data
    }

    fn chain(records: &[Vec<u8>]) -> Vec<u8> {
        let mut data: Vec<u8> = Vec::new();
        for (index, record) in records.iter().enumerate() {
            let mut record = record.clone();
            if index + 1 == records.len() {
                record[0..4].copy_from_slice(&0u32.to_le_bytes());
            }
            data.extend(record);
        }
        data
    }

    fn names(data: &[u8]) -> Result<Vec<String>, RecordError> {
        let mut result = Vec::new();
        for_each(data, |record| {
            result.push(String::from_utf16_lossy(&record.units().collect::<Vec<_>>()));
            Ok::<(), RecordError>(())
        })?;
        Ok(result)
    }

    #[test]
    fn skips_dot_entries_and_keeps_order() {
        let data = chain(&[record(".", 0, 0x10, 0, None), record("..", 0, 0x10, 0, None),
            record("b", 0, 0x20, 0, None), record("a", 0, 0x20, 0, None)]);
        assert_eq!(names(&data).unwrap(), ["b", "a"]);
    }

    #[test]
    fn rejects_malformed_records_like_the_reference() {
        let mut truncated = record("abc", 0, 0x20, 0, Some(0));
        truncated.truncate(90);
        let cases: Vec<(Vec<u8>, RecordError)> = vec![
            (vec![0u8; 40], RecordError::Truncated),
            (Vec::new(), RecordError::Truncated),
            (record("x", 0, 0x20, 0, Some(0))[..HEADER].to_vec(), RecordError::Invalid),
            (truncated, RecordError::Invalid),
            (record("a", -1, 0x20, 0, Some(0)), RecordError::Invalid),
            (chain(&[record("a", 0, 0x20, 0, Some(92)), record("b", 0, 0x20, 0, None)]), RecordError::InvalidOffset),
            (chain(&[record("abcdefghij", 0, 0x20, 0, Some(88)), record("b", 0, 0x20, 0, None)]), RecordError::InvalidOffset),
            (chain(&[record("ok", 0, 0x20, 0, None), record("a/b", 0, 0x20, 0, None)]), RecordError::InvalidName),
            (chain(&[record("ok", 0, 0x20, 0, None), record("a\\b", 0, 0x20, 0, None)]), RecordError::InvalidName),
            (chain(&[record("ok", 0, 0x20, 0, None), record("a\0b", 0, 0x20, 0, None)]), RecordError::InvalidName),
        ];
        for (data, expected) in cases {
            assert_eq!(names(&data).unwrap_err(), expected);
        }
    }

    #[test]
    fn odd_name_length_is_invalid() {
        let mut data = record("xy", 0, 0x20, 0, Some(0));
        data[60..64].copy_from_slice(&3u32.to_le_bytes());
        assert_eq!(names(&data).unwrap_err(), RecordError::Invalid);
    }

    #[test]
    fn names_end_at_the_longest_path() {
        let longest = "a".repeat(MAX_NAME_BYTES / 2);
        assert_eq!(names(&record(&longest, 0, 0x20, 0, Some(0))).unwrap(), [longest.clone()]);
        assert_eq!(names(&record(&(longest + "a"), 0, 0x20, 0, Some(0))).unwrap_err(), RecordError::Invalid);
    }

    #[test]
    fn latin1_detection_and_filetime_extremes() {
        let data = chain(&[record("caf\u{e9}", 0, 0x20, 0, None), record("\u{3a3}", 0, 0x20, 0, None)]);
        let mut flags = Vec::new();
        for_each(&data, |record| {
            flags.push(record.latin1);
            Ok::<(), RecordError>(())
        })
        .unwrap();
        assert_eq!(flags, [true, false]);
        assert_eq!(filetime_ns(EPOCH), 0);
        assert_eq!(filetime_ns(i64::MIN), (i64::MIN as i128 - EPOCH as i128) * 100);
        assert_eq!(filetime_ns(i64::MAX), (i64::MAX as i128 - EPOCH as i128) * 100);
    }
}
