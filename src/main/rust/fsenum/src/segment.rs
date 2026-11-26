//! Entry storage: fixed-capacity segments, immutable once published, so the
//! threads that read them never see a reallocation. Entry `e` lives in segment
//! `e >> SEG_SHIFT` at `e & (SEG - 1)`.

use crate::record::Record;
use crate::sort::Ordered;
use crate::Failure;
use std::sync::Arc;

pub const SEG_SHIFT: usize = 12;
pub const SEG: usize = 1 << SEG_SHIFT;
const UTF16: u16 = 0x8000;

/// The values stored for one entry, after link follow-up.
#[derive(Clone, Copy, PartialEq, Eq)]
pub struct Values {
    pub is_dir: bool,
    pub size: u64,
    /// Raw FILETIME values; converted to Unix nanoseconds for Python.
    pub modified: i64,
    pub created: i64,
    pub attributes: u32,
    pub identity: [u8; 16],
}

#[derive(Default)]
pub struct Segment {
    /// Latin-1 bytes, or UTF-16LE bytes when the name has a unit above 255.
    pub names: Vec<u8>,
    pub name_starts: Vec<u32>,
    /// Length in characters (Latin-1) or units (UTF-16), with `UTF16` set for the latter.
    pub name_meta: Vec<u16>,
    pub is_dir: Vec<u8>,
    pub sizes: Vec<u64>,
    pub modified: Vec<i64>,
    pub created: Vec<i64>,
    pub attributes: Vec<u32>,
    pub identities: Vec<[u8; 16]>,
}

pub enum Name<'a> {
    Latin1(&'a [u8]),
    Utf16(&'a [u8]),
}

fn reserve<T>(vector: &mut Vec<T>, additional: usize) -> Result<(), Failure> {
    vector.try_reserve_exact(additional).map_err(|_| Failure::Memory)
}

impl Segment {
    pub fn new() -> Result<Segment, Failure> {
        let mut segment = Segment::default();
        reserve(&mut segment.names, SEG * 32)?;
        reserve(&mut segment.name_starts, SEG)?;
        reserve(&mut segment.name_meta, SEG)?;
        reserve(&mut segment.is_dir, SEG)?;
        reserve(&mut segment.sizes, SEG)?;
        reserve(&mut segment.modified, SEG)?;
        reserve(&mut segment.created, SEG)?;
        reserve(&mut segment.attributes, SEG)?;
        reserve(&mut segment.identities, SEG)?;
        Ok(segment)
    }

    #[inline]
    pub fn len(&self) -> usize {
        self.is_dir.len()
    }

    #[inline]
    pub fn is_full(&self) -> bool {
        self.len() == SEG
    }

    /// Appends an entry; the record supplies the name, `values` the rest.
    /// A name has at most `record::MAX_NAME_BYTES`, so its units fit `name_meta`
    /// and a segment's names stay far below 4 GiB.
    pub fn push(&mut self, record: &Record<'_>, values: &Values) -> Result<(), Failure> {
        let start = self.names.len();
        let units = record.name.len() / 2;
        debug_assert!(units < UTF16 as usize);
        let stored = if record.latin1 { units } else { record.name.len() };
        if self.names.capacity() - start < stored {
            self.names.try_reserve(stored.max(SEG * 16)).map_err(|_| Failure::Memory)?;
        }
        if record.latin1 {
            let target = &mut self.names.spare_capacity_mut()[..units];
            for (byte, pair) in target.iter_mut().zip(record.name.chunks_exact(2)) {
                byte.write(pair[0]);
            }
            // SAFETY: the `units` bytes after `start` were just written.
            unsafe { self.names.set_len(start + units) };
        } else {
            self.names.extend_from_slice(record.name);
        }
        self.name_starts.push(start as u32);
        self.name_meta.push(units as u16 | if record.latin1 { 0 } else { UTF16 });
        self.is_dir.push(values.is_dir as u8);
        self.sizes.push(values.size);
        self.modified.push(values.modified);
        self.created.push(values.created);
        self.attributes.push(values.attributes);
        self.identities.push(values.identity);
        Ok(())
    }

    #[inline]
    pub fn name(&self, local: usize) -> Name<'_> {
        let start = self.name_starts[local] as usize;
        let meta = self.name_meta[local];
        let units = (meta & !UTF16) as usize;
        if meta & UTF16 == 0 {
            Name::Latin1(&self.names[start..start + units])
        } else {
            Name::Utf16(&self.names[start..start + 2 * units])
        }
    }

    #[inline]
    pub fn values(&self, local: usize) -> Values {
        Values {
            is_dir: self.is_dir[local] != 0,
            size: self.sizes[local],
            modified: self.modified[local],
            created: self.created[local],
            attributes: self.attributes[local],
            identity: self.identities[local],
        }
    }

    /// Whether entry `local` has exactly this record's name and these values.
    #[inline]
    pub fn equals(&self, local: usize, record: &Record<'_>, values: &Values) -> bool {
        if self.values(local) != *values {
            return false;
        }
        match self.name(local) {
            Name::Latin1(bytes) => record.latin1 && bytes.len() * 2 == record.name.len()
                && bytes.iter().zip(record.name.chunks_exact(2)).fold(true, |same, (a, pair)| same & (*a == pair[0])),
            Name::Utf16(bytes) => !record.latin1 && bytes == record.name,
        }
    }
}

/// A folder's entries and Name order, attached to its `Listing` as `_native`.
pub struct Table {
    pub segments: Vec<Arc<Segment>>,
    pub count: usize,
    pub scope: (u64, [u8; 16]),
    pub ordered: Ordered,
}

impl Table {
    #[inline]
    pub fn segment(&self, entry: usize) -> (&Segment, usize) {
        (&self.segments[entry >> SEG_SHIFT], entry & (SEG - 1))
    }

    #[inline]
    pub fn attributes(&self, entry: usize) -> u32 {
        let (segment, local) = self.segment(entry);
        segment.attributes[local]
    }
}
