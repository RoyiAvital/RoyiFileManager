//! Natural sort keys equal to fman.impl.util.natural.natural_key:
//!
//!     parts = re.split(r'(\d+)', name.lower())
//!     each digit run: values (unicodedata.decimal), lstrip('0') or '0';
//!       len <= 6 -> '0' + digits.zfill(6)
//!       otherwise -> '1' + '1' * len(str(len)) + '0' + str(len) + digits
//!
//! Lower-casing follows str.lower() through tables generated from the shipped
//! Python (generate_unicode.py), including its Final_Sigma rule. Keys are
//! emitted to a `Sink`: WTF-8 bytes for sorting (bytewise order equals code
//! point order, lone surrogates included) or code points for Python strings.

use crate::unicode::{CASED, CASE_IGNORABLE, DECIMAL, LATIN1_LOWER, LOWER};

pub trait Sink {
    fn push(&mut self, code: u32);
    #[inline]
    fn push_ascii(&mut self, byte: u8) {
        self.push(byte as u32);
    }
}

/// Generalized UTF-8: surrogates are encoded like other code points, which
/// keeps byte order equal to code point order.
pub struct Wtf8<'a>(pub &'a mut Vec<u8>);

impl Sink for Wtf8<'_> {
    #[inline]
    fn push(&mut self, code: u32) {
        let out = &mut *self.0;
        if code < 0x80 {
            out.push(code as u8);
        } else if code < 0x800 {
            out.extend_from_slice(&[0xC0 | (code >> 6) as u8, 0x80 | (code & 0x3F) as u8]);
        } else if code < 0x10000 {
            out.extend_from_slice(&[0xE0 | (code >> 12) as u8, 0x80 | ((code >> 6) & 0x3F) as u8,
                0x80 | (code & 0x3F) as u8]);
        } else {
            out.extend_from_slice(&[0xF0 | (code >> 18) as u8, 0x80 | ((code >> 12) & 0x3F) as u8,
                0x80 | ((code >> 6) & 0x3F) as u8, 0x80 | (code & 0x3F) as u8]);
        }
    }
    #[inline]
    fn push_ascii(&mut self, byte: u8) {
        self.0.push(byte);
    }
}

pub struct Points<'a>(pub &'a mut Vec<u32>);

impl Sink for Points<'_> {
    #[inline]
    fn push(&mut self, code: u32) {
        self.0.push(code);
    }
}

fn in_ranges(table: &[(u32, u32)], code: u32) -> bool {
    let index = table.partition_point(|&(first, _)| first <= code);
    index > 0 && code <= table[index - 1].1
}

/// Decimal value of a code point re's `\d` matches, else None.
#[inline]
pub fn decimal(code: u32) -> Option<u8> {
    if code < 0x80 {
        return if (b'0' as u32..=b'9' as u32).contains(&code) { Some((code - b'0' as u32) as u8) } else { None };
    }
    if code < DECIMAL[1].0 {
        return None;
    }
    let index = DECIMAL.partition_point(|&(first, _, _)| first <= code);
    let (first, last, value) = DECIMAL[index - 1];
    if code <= last { Some(value + (code - first) as u8) } else { None }
}

/// chr(code).lower(), one to three code points, U+03A3 excluded (contextual).
#[inline]
fn lower_into(code: u32, out: &mut Vec<u32>) {
    if code < 256 {
        out.push(LATIN1_LOWER[code as usize] as u32);
        return;
    }
    match LOWER.binary_search_by_key(&code, |&(source, _)| source) {
        Ok(index) => {
            for &mapped in LOWER[index].1.iter().take_while(|&&mapped| mapped != 0) {
                out.push(mapped);
            }
        }
        Err(_) => out.push(code),
    }
}

/// str.lower()'s choice for U+03A3 at `index` of `text`: final sigma when a
/// cased character precedes it and none follows, skipping case-ignorable ones.
fn final_sigma(text: &[u32], index: usize) -> bool {
    let before = text[..index].iter().rev().find(|&&code| !in_ranges(&CASE_IGNORABLE, code));
    match before {
        Some(&code) if in_ranges(&CASED, code) => {}
        _ => return false,
    }
    match text[index + 1..].iter().find(|&&code| !in_ranges(&CASE_IGNORABLE, code)) {
        None => true,
        Some(&code) => !in_ranges(&CASED, code),
    }
}

fn emit_digits<S: Sink>(digits: &[u8], sink: &mut S) {
    let mut first = 0;
    while first + 1 < digits.len() && digits[first] == 0 {
        first += 1;
    }
    let significant = digits.len() - first;
    if significant <= 6 {
        for _ in significant..7 {
            sink.push_ascii(b'0');
        }
    } else {
        let mut length = [0u8; 20];
        let mut cursor = length.len();
        let mut value = significant;
        while value > 0 {
            cursor -= 1;
            length[cursor] = b'0' + (value % 10) as u8;
            value /= 10;
        }
        sink.push_ascii(b'1');
        for _ in cursor..length.len() {
            sink.push_ascii(b'1');
        }
        sink.push_ascii(b'0');
        for &byte in &length[cursor..] {
            sink.push_ascii(byte);
        }
    }
    for &digit in &digits[first..] {
        sink.push_ascii(b'0' + digit);
    }
}

/// Reusable buffers for one key builder.
#[derive(Default)]
pub struct Scratch {
    points: Vec<u32>,
    lowered: Vec<u32>,
    digits: Vec<u8>,
}

/// A name stored as Latin-1. No Latin-1 character is a decimal digit except
/// ASCII 0-9, none is U+03A3, and every lower-case mapping stays in Latin-1.
pub fn latin1<S: Sink>(name: &[u8], scratch: &mut Scratch, sink: &mut S) {
    let mut index = 0;
    while index < name.len() {
        let byte = name[index];
        if byte.is_ascii_digit() {
            scratch.digits.clear();
            while index < name.len() && name[index].is_ascii_digit() {
                scratch.digits.push(name[index] - b'0');
                index += 1;
            }
            emit_digits(&scratch.digits, sink);
        } else {
            let lowered = LATIN1_LOWER[byte as usize];
            if lowered < 0x80 { sink.push_ascii(lowered) } else { sink.push(lowered as u32) }
            index += 1;
        }
    }
}

/// `latin1` into WTF-8 bytes without per-byte bookkeeping: the scan's hot
/// path, since most names are Latin-1. Each name byte yields at most 7 key
/// bytes (a lone digit becomes "0000000d"), so one reservation covers it.
pub fn latin1_wtf8(name: &[u8], out: &mut Vec<u8>) -> Result<(), crate::Failure> {
    let bound = name.len() * 7 + 8;
    out.try_reserve(bound).map_err(|_| crate::Failure::Memory)?;
    let start = out.len();
    // SAFETY: `bound` bytes from `start` are reserved and every write below
    // stays within the key's bound; only written bytes become visible.
    unsafe {
        let target = out.as_mut_ptr().add(start);
        let mut written = 0usize;
        let mut index = 0usize;
        while index < name.len() {
            // Eight ASCII non-digits at a time: lower-case A-Z (SWAR).
            if index + 8 <= name.len() {
                const HIGH: u64 = 0x8080_8080_8080_8080;
                let word = u64::from_le_bytes(name[index..index + 8].try_into().unwrap());
                let at_least = |byte: u8| word.wrapping_add(0x0101_0101_0101_0101 * (0x80 - byte) as u64) & HIGH;
                let digits = at_least(b'0') & !at_least(b'9' + 1);
                if word & HIGH == 0 && digits == 0 {
                    let upper = at_least(b'A') & !at_least(b'Z' + 1);
                    std::ptr::copy_nonoverlapping((word | upper >> 2).to_le_bytes().as_ptr(), target.add(written), 8);
                    written += 8;
                    index += 8;
                    continue;
                }
            }
            let byte = *name.get_unchecked(index);
            if byte.wrapping_sub(b'0') < 10 {
                let first = index;
                index += 1;
                while index < name.len() && name.get_unchecked(index).wrapping_sub(b'0') < 10 {
                    index += 1;
                }
                let mut leading = first;
                while leading + 1 < index && *name.get_unchecked(leading) == b'0' {
                    leading += 1;
                }
                let significant = index - leading;
                if significant <= 6 {
                    // '0' + zfill(6): seven bytes, digits right-aligned.
                    std::ptr::write_bytes(target.add(written), b'0', 7 - significant);
                    written += 7 - significant;
                } else {
                    let mut length = [0u8; 20];
                    let mut cursor = length.len();
                    let mut value = significant;
                    while value > 0 {
                        cursor -= 1;
                        length[cursor] = b'0' + (value % 10) as u8;
                        value /= 10;
                    }
                    let digits = length.len() - cursor;
                    std::ptr::write_bytes(target.add(written), b'1', 1 + digits);
                    *target.add(written + 1 + digits) = b'0';
                    std::ptr::copy_nonoverlapping(length.as_ptr().add(cursor), target.add(written + 2 + digits), digits);
                    written += 2 + 2 * digits;
                }
                std::ptr::copy_nonoverlapping(name.as_ptr().add(leading), target.add(written), significant);
                written += significant;
            } else if byte < 0x80 {
                *target.add(written) = byte | (((byte.wrapping_sub(b'A') < 26) as u8) << 5);
                written += 1;
                index += 1;
            } else {
                let lowered = LATIN1_LOWER[byte as usize];
                if lowered < 0x80 {
                    *target.add(written) = lowered;
                    written += 1;
                } else {
                    *target.add(written) = 0xC0 | lowered >> 6;
                    *target.add(written + 1) = 0x80 | (lowered & 0x3F);
                    written += 2;
                }
                index += 1;
            }
        }
        debug_assert!(written <= bound);
        out.set_len(start + written);
    }
    Ok(())
}

/// A name as UTF-16 units; valid surrogate pairs combine, lone ones stay, as
/// the 'surrogatepass' decoder does.
pub fn utf16<S: Sink>(units: impl Iterator<Item = u16>, scratch: &mut Scratch, sink: &mut S) {
    let mut points = std::mem::take(&mut scratch.points);
    points.clear();
    let mut pending: Option<u16> = None;
    for unit in units {
        if let Some(high) = pending.take() {
            if (0xDC00..0xE000).contains(&unit) {
                points.push(0x10000 + (((high as u32) - 0xD800) << 10) + (unit as u32 - 0xDC00));
                continue;
            }
            points.push(high as u32);
        }
        if (0xD800..0xDC00).contains(&unit) {
            pending = Some(unit);
        } else {
            points.push(unit as u32);
        }
    }
    if let Some(high) = pending {
        points.push(high as u32);
    }
    code_points(&points, scratch, sink);
    scratch.points = points;
}

/// A name as code points (a Python str).
pub fn code_points<S: Sink>(text: &[u32], scratch: &mut Scratch, sink: &mut S) {
    let lowered = &mut scratch.lowered;
    lowered.clear();
    for (index, &code) in text.iter().enumerate() {
        if code < 0x80 {
            lowered.push(if (b'A' as u32..=b'Z' as u32).contains(&code) { code + 32 } else { code });
        } else if code == 0x3A3 {
            lowered.push(if final_sigma(text, index) { 0x3C2 } else { 0x3C3 });
        } else {
            lower_into(code, lowered);
        }
    }
    let mut index = 0;
    while index < lowered.len() {
        let code = lowered[index];
        if decimal(code).is_none() {
            sink.push(code);
            index += 1;
            continue;
        }
        scratch.digits.clear();
        while index < lowered.len() {
            match decimal(lowered[index]) {
                Some(value) => scratch.digits.push(value),
                None => break,
            }
            index += 1;
        }
        emit_digits(&scratch.digits, sink);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn key(text: &str) -> String {
        let points: Vec<u32> = text.chars().map(|c| c as u32).collect();
        let mut out = Vec::new();
        code_points(&points, &mut Scratch::default(), &mut Points(&mut out));
        out.into_iter().map(|code| char::from_u32(code).unwrap()).collect()
    }

    #[test]
    #[ignore]
    fn bench_latin1_keys() {
        let names: Vec<Vec<u8>> = (0..200_000)
            .map(|index: usize| format!("common_{}_{:024x}_{:08}.txt", "a".repeat(72), index * 7919, index).into_bytes())
            .collect();
        for _ in 0..3 {
            let started = std::time::Instant::now();
            let mut out = Vec::with_capacity(32 << 20);
            for name in &names {
                latin1_wtf8(name, &mut out).unwrap();
            }
            eprintln!("latin1_wtf8: {:.1} ms for {} names, {} key bytes", started.elapsed().as_secs_f64() * 1e3,
                names.len(), out.len());
        }
    }

    #[test]
    fn digit_runs_match_the_reference() {
        assert_eq!(key("File2.txt"), "file0000002.txt");
        assert_eq!(key("file02"), "file0000002");
        assert_eq!(key("000"), "0000000");
        assert_eq!(key("file1000000"), "file11071000000");
        assert_eq!(key("v\u{662}\u{663}"), "v0000023");
        assert_eq!(key(&("a".to_owned() + &"9".repeat(80))), "a111080".to_owned() + &"9".repeat(80));
    }

    #[test]
    fn final_sigma_follows_context() {
        assert_eq!(key("\u{3a3}"), "\u{3c3}");
        assert_eq!(key("A\u{3a3}"), "a\u{3c2}");
        assert_eq!(key("A\u{3a3}B"), "a\u{3c3}b");
        assert_eq!(key("\u{130}"), "i\u{307}");
    }

    #[test]
    fn latin1_and_utf16_paths_agree_with_code_points() {
        for text in ["Stra\u{df}e_CAF\u{c9} 12", "plain 007", "\u{ff}\u{fe} 1", "a1234567b0000000000c9", "", "0",
            "x12345678901234567890123", "ABCDEFGHIJKLMNOPQRSTUVWXYZ@[`{ mixed CASE 0123 abcdefghij",
            "@@@@@@@@[[[[[[[[````````{{{{{{{{////////::::::::9"] {
            let bytes: Vec<u8> = text.chars().map(|c| c as u8).collect();
            let mut a = Vec::new();
            latin1(&bytes, &mut Scratch::default(), &mut Wtf8(&mut a));
            let mut fast = vec![b'#'];
            latin1_wtf8(&bytes, &mut fast).unwrap();
            assert_eq!(&fast[1..], a.as_slice());
            let mut b = Vec::new();
            utf16(text.encode_utf16(), &mut Scratch::default(), &mut Wtf8(&mut b));
            assert_eq!(a, b);
            assert_eq!(String::from_utf8(a).unwrap(), key(text));
        }
        let mut lone = Vec::new();
        utf16([0x61, 0xDC80, 0xD83D, 0xDE00, 0xD800].into_iter(), &mut Scratch::default(), &mut Points(&mut lone));
        assert_eq!(lone, [0x61, 0xDC80, 0x1F600, 0xD800]);
    }

    #[test]
    fn wtf8_order_is_code_point_order() {
        let codes = [0x41, 0x7F, 0x80, 0x7FF, 0x800, 0xD7FF, 0xD800, 0xDFFF, 0xE000, 0xFFFF, 0x10000, 0x10FFFF];
        let encoded: Vec<Vec<u8>> = codes.iter().map(|&code| {
            let mut out = Vec::new();
            Wtf8(&mut out).push(code);
            out
        }).collect();
        assert!(encoded.windows(2).all(|pair| pair[0] < pair[1]));
    }
}
