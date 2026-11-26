//! Name order: directories first, natural keys ascending, ties in enumeration
//! order; Python's stable `sorted(range(n), key=keys.__getitem__)` over
//! ('0' or '1') + natural_key(name).
//!
//! Keys arrive one segment at a time while the folder is still being read;
//! the sort starts once every key exists. It is a most-significant-first sort
//! on 8-byte key chunks that compares integers only:
//!
//! 1. Items are bucketed by their first two key bytes; contiguous bucket
//!    ranges of about equal size go to up to `threads` threads.
//! 2. Each bucket is sorted by its 8-byte chunk. Every run of equal chunks is
//!    resolved by skipping the bytes all its keys share (their longest common
//!    prefix), loading the next 8-byte chunk and sorting again, recursively.
//! 3. Keys that end together are equal: they are ordered by entry index and
//!    flagged as ties, which gives the descending order without re-sorting.
//!
//! Long shared stems ("IMG_2024...", "common_aaaa...") therefore cost one
//! prefix scan per group instead of one byte comparison per sort step.

use crate::segment::{SEG, SEG_SHIFT};
use crate::Failure;
use std::sync::Mutex;

const TIED: u32 = 1 << 31;

#[derive(Clone, Copy, Default)]
pub struct Item {
    /// Eight key bytes at the current offset, big-endian, zero-padded.
    pub chunk: u64,
    pub entry: u32,
    /// Key length in bytes; `TIED` set when the key equals the previous item's.
    pub length: u32,
}

/// The keys of one segment: key `i` is `bytes[ends[i - 1]..ends[i]]`.
#[derive(Clone, Copy)]
struct KeySeg<'a> {
    bytes: &'a [u8],
    ends: &'a [u32],
}

impl<'a> KeySeg<'a> {
    #[inline]
    fn key(&self, local: usize) -> &'a [u8] {
        let start = if local == 0 { 0 } else { self.ends[local - 1] as usize };
        &self.bytes[start..self.ends[local] as usize]
    }
}

/// The keys of a folder, by segment.
struct Keys<'a>(&'a [KeySeg<'a>]);

impl Keys<'_> {
    #[inline]
    fn key(&self, entry: u32) -> &[u8] {
        let entry = entry as usize;
        self.0[entry >> SEG_SHIFT].key(entry & (SEG - 1))
    }
}

/// Eight bytes of `key` from `offset`, big-endian, zero past the end. Keys
/// hold no NUL byte, so a shorter key sorts first, as in string order.
#[inline]
pub fn chunk_at(key: &[u8], offset: usize) -> u64 {
    let mut bytes = [0u8; 8];
    if offset < key.len() {
        let length = (key.len() - offset).min(8);
        bytes[..length].copy_from_slice(&key[offset..offset + length]);
    }
    u64::from_be_bytes(bytes)
}

/// Amortized: a builder extends its vectors once per segment, and an exact
/// reservation would copy them whole each time.
fn reserve<T>(vector: &mut Vec<T>, additional: usize) -> Result<(), Failure> {
    vector.try_reserve(additional).map_err(|_| Failure::Memory)
}

/// Length of the common prefix of `a` and `b`, at most `limit`; eight bytes at a time.
#[inline]
fn common_prefix(a: &[u8], b: &[u8], limit: usize) -> usize {
    let limit = limit.min(a.len()).min(b.len());
    let mut index = 0;
    while index + 8 <= limit {
        let difference = u64::from_le_bytes(a[index..index + 8].try_into().unwrap())
            ^ u64::from_le_bytes(b[index..index + 8].try_into().unwrap());
        if difference != 0 {
            return index + (difference.trailing_zeros() / 8) as usize;
        }
        index += 8;
    }
    while index < limit && a[index] == b[index] {
        index += 1;
    }
    index
}

/// Sorts by chunk: large groups split by the chunk's top byte first.
fn sort_by_chunk(items: &mut [Item]) {
    if items.len() >= 2048 {
        let mut counts = [0usize; 257];
        for item in items.iter() {
            counts[(item.chunk >> 56) as usize + 1] += 1;
        }
        if counts.iter().all(|&count| count < items.len()) {
            for bucket in 0..256 {
                counts[bucket + 1] += counts[bucket];
            }
            let mut sorted = Vec::new();
            if sorted.try_reserve_exact(items.len()).is_ok() {
                sorted.resize(items.len(), Item::default());
                let mut cursor = counts;
                for item in items.iter() {
                    let bucket = (item.chunk >> 56) as usize;
                    sorted[cursor[bucket]] = *item;
                    cursor[bucket] += 1;
                }
                items.copy_from_slice(&sorted);
                for bucket in 0..256 {
                    items[counts[bucket]..counts[bucket + 1]].sort_unstable_by_key(|item| item.chunk);
                }
                return;
            }
        }
    }
    items.sort_unstable_by_key(|item| item.chunk);
}

/// Orders `items` (sorted by their chunk at `offset`) by full key, then entry.
fn refine(keys: &Keys, items: &mut [Item], offset: usize) {
    let mut start = 0;
    while start < items.len() {
        let chunk = items[start].chunk;
        let mut end = start + 1;
        while end < items.len() && items[end].chunk == chunk {
            end += 1;
        }
        if end - start > 1 {
            resolve(keys, &mut items[start..end], offset);
        }
        start = end;
    }
}

/// `group` shares its chunk at `offset` and every byte before it.
fn resolve(keys: &Keys, group: &mut [Item], offset: usize) {
    let next = offset + 8;
    if group.iter().all(|item| (item.length & !TIED) as usize <= next) {
        // Equal keys: enumeration order, all but the first tied.
        group.sort_unstable_by_key(|item| item.entry);
        for item in &mut group[1..] {
            item.length |= TIED;
        }
        return;
    }
    let tail = |entry: u32| {
        let key = keys.key(entry);
        if key.len() > next { &key[next..] } else { &[][..] }
    };
    let first = tail(group[0].entry);
    let mut common = first.len();
    for item in &group[1..] {
        common = common_prefix(first, tail(item.entry), common);
        if common == 0 {
            break;
        }
    }
    let offset = next + common;
    for item in group.iter_mut() {
        item.chunk = chunk_at(keys.key(item.entry), offset);
    }
    sort_by_chunk(group);
    refine(keys, group, offset);
}

/// Sorts one group (directories or files), given as the builders' parts, on
/// up to `threads` threads.
fn sort_group(keys: &Keys, parts: &[&[Item]], threads: usize) -> Result<Vec<Item>, Failure> {
    const BUCKETS: usize = 1 << 16;
    let total: usize = parts.iter().map(|part| part.len()).sum();
    let mut sorted = Vec::new();
    reserve(&mut sorted, total)?;
    // Below this the 65,536-bucket table (512 KiB) costs more than it saves.
    if total < 1 << 12 {
        for part in parts {
            sorted.extend_from_slice(part);
        }
        sort_by_chunk(&mut sorted);
        refine(keys, &mut sorted, 0);
        return Ok(sorted);
    }
    let mut starts = Vec::new();
    reserve(&mut starts, BUCKETS + 1)?;
    starts.resize(BUCKETS + 1, 0usize);
    // The buckets are the two bytes after the leading bytes every chunk
    // shares: digit-led keys all start with zero padding, and names often
    // share a short stem; their first two bytes would give one bucket.
    let sample = parts.iter().copied().flatten().next().map_or(0, |item| item.chunk);
    let differing = parts.iter().copied().flatten().fold(0, |bits, item| bits | (item.chunk ^ sample));
    let shift = (differing.leading_zeros() / 8 * 8).min(48);
    let bucket_of = |item: &Item| ((item.chunk << shift) >> 48) as usize;
    for item in parts.iter().copied().flatten() {
        starts[bucket_of(item) + 1] += 1;
    }
    for bucket in 0..BUCKETS {
        starts[bucket + 1] += starts[bucket];
    }
    let mut cursor = Vec::new();
    reserve(&mut cursor, BUCKETS)?;
    cursor.extend_from_slice(&starts[..BUCKETS]);
    sorted.resize(total, Item::default());
    for item in parts.iter().copied().flatten() {
        let bucket = bucket_of(item);
        sorted[cursor[bucket]] = *item;
        cursor[bucket] += 1;
    }
    drop(cursor);
    let starts = &starts;
    let sort_buckets = move |slice: &mut [Item], base: usize, first: usize, last: usize| {
        for bucket in first..last {
            let range = &mut slice[starts[bucket] - base..starts[bucket + 1] - base];
            if range.len() > 1 {
                sort_by_chunk(range);
                refine(keys, range, 0);
            }
        }
    };
    let workers = if total >= 1 << 14 { threads.max(1) } else { 1 };
    // The work: contiguous bucket ranges holding about total / workers items each.
    let mut work = Vec::new();
    reserve(&mut work, workers)?;
    let mut rest: &mut [Item] = &mut sorted;
    let mut first = 0;
    for worker in 1..=workers {
        let last = if worker == workers { BUCKETS } else {
            starts.partition_point(|&start| start < total * worker / workers).clamp(first, BUCKETS)
        };
        let base = starts[first];
        let (slice, tail) = rest.split_at_mut(starts[last] - base);
        rest = tail;
        if !slice.is_empty() {
            work.push((slice, base, first, last));
        }
        first = last;
    }
    let helpers = work.len().saturating_sub(1);
    let work = Mutex::new(work);
    let run = || loop {
        let next = work.lock().unwrap_or_else(|poisoned| poisoned.into_inner()).pop();
        let Some((slice, base, first, last)) = next else { break };
        sort_buckets(slice, base, first, last);
    };
    std::thread::scope(|scope| {
        // A helper that cannot start leaves its range to the others.
        for _ in 0..helpers {
            let _ = std::thread::Builder::new().name("fsenum-sort".into()).spawn_scoped(scope, &run);
        }
        run();
    });
    drop(work);
    Ok(sorted)
}

/// The finished order of a folder.
pub struct Ordered {
    /// Ascending order: directories first.
    pub order: Vec<u32>,
    /// Bit `p` set: the key at position `p` equals the key at `p - 1` (same group).
    pub ties: Vec<u64>,
    pub directories: usize,
}

impl Ordered {
    #[inline]
    pub fn tied(&self, position: usize) -> bool {
        self.ties[position >> 6] >> (position & 63) & 1 != 0
    }

    /// Descending order: directories still first; within each group the runs
    /// of equal keys reversed, each run keeping enumeration order (stable
    /// `sorted(..., reverse=True)`).
    pub fn descending(&self) -> Result<Vec<u32>, Failure> {
        let mut out = Vec::new();
        reserve(&mut out, self.order.len())?;
        for (start, end) in [(0, self.directories), (self.directories, self.order.len())] {
            let mut run_end = end;
            let mut position = end;
            while position > start {
                position -= 1;
                if position == start || !self.tied(position) {
                    out.extend_from_slice(&self.order[position..run_end]);
                    run_end = position;
                }
            }
        }
        Ok(out)
    }
}

/// What one key builder collects, segments in any order: their keys and a
/// sort item per entry. The keys share one buffer: a buffer per segment made
/// the scan end with a slow free per segment (2.5 ms for 200,000 entries).
#[derive(Default)]
pub struct Sorter {
    bytes: Vec<u8>,
    /// Per segment: its index, where its keys start in `bytes` and each key's end from there.
    segments: Vec<(usize, usize, Vec<u32>)>,
    /// Directories, then files.
    groups: [Vec<Item>; 2],
}

impl Sorter {
    /// Adds segment `index` with one entry per `is_dir` flag; `append(local, bytes)`
    /// appends the key of entry `local`. Every segment but the folder's last
    /// holds `SEG` entries.
    pub fn add<E: From<Failure>>(&mut self, index: usize, is_dir: &[u8],
        mut append: impl FnMut(usize, &mut Vec<u8>) -> Result<(), E>) -> Result<(), E> {
        let start = self.bytes.len();
        let mut ends = Vec::new();
        reserve(&mut ends, is_dir.len())?;
        for local in 0..is_dir.len() {
            append(local, &mut self.bytes)?;
            ends.push((self.bytes.len() - start) as u32);
        }
        let keys = KeySeg { bytes: &self.bytes[start..], ends: &ends };
        let base = index << SEG_SHIFT;
        let directories = is_dir.iter().filter(|&&flag| flag != 0).count();
        reserve(&mut self.groups[0], directories)?;
        reserve(&mut self.groups[1], is_dir.len() - directories)?;
        for (local, &flag) in is_dir.iter().enumerate() {
            let key = keys.key(local);
            self.groups[(flag == 0) as usize].push(Item {
                chunk: chunk_at(key, 0),
                entry: (base + local) as u32,
                length: key.len() as u32,
            });
        }
        reserve(&mut self.segments, 1)?;
        self.segments.push((index, start, ends));
        Ok(())
    }

    /// Sorts what the builders collected: together, the segments 0, 1, ...
    /// without gaps. The builders keep the keys; the caller drops them.
    pub fn finish(builders: &[Sorter], threads: usize) -> Result<Ordered, Failure> {
        let mut segments = Vec::new();
        reserve(&mut segments, builders.iter().map(|builder| builder.segments.len()).sum())?;
        for builder in builders {
            for (index, start, ends) in &builder.segments {
                segments.push((*index, KeySeg { bytes: &builder.bytes[*start..], ends }));
            }
        }
        segments.sort_unstable_by_key(|(index, _)| *index);
        debug_assert!(segments.iter().enumerate().all(|(position, (index, _))| position == *index));
        let mut ordered = Vec::new();
        reserve(&mut ordered, segments.len())?;
        ordered.extend(segments.iter().map(|(_, keys)| *keys));
        let keys = Keys(&ordered);
        let count: usize = builders.iter().map(|builder| builder.groups[0].len() + builder.groups[1].len()).sum();
        let mut order = Vec::new();
        reserve(&mut order, count)?;
        let mut ties = Vec::new();
        reserve(&mut ties, count.div_ceil(64))?;
        ties.resize(count.div_ceil(64), 0u64);
        let mut directories = 0;
        let mut parts = Vec::new();
        reserve(&mut parts, builders.len())?;
        for group in 0..2 {
            parts.clear();
            parts.extend(builders.iter().map(|builder| builder.groups[group].as_slice()));
            let items = sort_group(&keys, &parts, threads)?;
            if group == 0 {
                directories = items.len();
            }
            for item in &items {
                if item.length & TIED != 0 {
                    let position = order.len();
                    ties[position >> 6] |= 1 << (position & 63);
                }
                order.push(item.entry);
            }
        }
        Ok(Ordered { order, ties, directories })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::keys::{code_points, Scratch, Wtf8};

    /// Two builders, each adding every other segment from the last one down,
    /// as the key threads may; the order must not depend on that.
    fn sorter_for(names: &[&str], dirs: &[bool]) -> Ordered {
        let mut sorters = [Sorter::default(), Sorter::default()];
        let mut scratch = Scratch::default();
        let segments: Vec<_> = names.chunks(SEG).zip(dirs.chunks(SEG)).enumerate().collect();
        for (index, (chunk, flags)) in segments.into_iter().rev() {
            let flags: Vec<u8> = flags.iter().map(|&flag| flag as u8).collect();
            sorters[index % 2].add(index, &flags, |local, bytes| {
                let points: Vec<u32> = chunk[local].chars().map(|c| c as u32).collect();
                code_points(&points, &mut scratch, &mut Wtf8(bytes));
                Ok::<(), Failure>(())
            }).unwrap();
        }
        Sorter::finish(&sorters, 4).unwrap()
    }

    fn reference(names: &[&str], dirs: &[bool], ascending: bool) -> Vec<u32> {
        let keys: Vec<String> = names.iter().zip(dirs).map(|(name, &dir)| {
            let points: Vec<u32> = name.chars().map(|c| c as u32).collect();
            let mut bytes = vec![if dir ^ ascending { b'1' } else { b'0' }];
            code_points(&points, &mut Scratch::default(), &mut Wtf8(&mut bytes));
            String::from_utf8(bytes).unwrap()
        }).collect();
        let mut order: Vec<u32> = (0..names.len() as u32).collect();
        // Stable sort; reverse=True keeps equal keys in input order.
        if ascending {
            order.sort_by(|&a, &b| keys[a as usize].cmp(&keys[b as usize]));
        } else {
            order.sort_by(|&a, &b| keys[b as usize].cmp(&keys[a as usize]));
        }
        order
    }

    fn check(owned: &[String], every: usize) {
        let names: Vec<&str> = owned.iter().map(String::as_str).collect();
        let dirs: Vec<bool> = (0..names.len()).map(|index| index % every == 0).collect();
        let ordered = sorter_for(&names, &dirs);
        assert_eq!(ordered.order, reference(&names, &dirs, true));
        assert_eq!(ordered.descending().unwrap(), reference(&names, &dirs, false));
    }

    #[test]
    fn matches_stable_sort_with_shared_stems_and_duplicates() {
        let mut owned = Vec::new();
        let mut state = 12345u64;
        for index in 0..(5 * SEG + 777) {
            state = state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            let pick = (state >> 33) as usize;
            owned.push(match pick % 7 {
                0 => format!("file{}", pick % 300),
                1 => format!("File{:03}", pick % 300),
                2 => format!("common_{}", "a".repeat(pick % 40)),
                3 => format!("common_{}_{}", "a".repeat(60), pick % 97),
                4 => format!("x{}", index),
                5 => "dup".to_string(),
                _ => "ab".repeat(pick % 12),
            });
        }
        check(&owned, 7);
        check(&owned, 1);
    }

    #[test]
    fn keys_ending_inside_a_chunk_and_exact_multiples_of_eight() {
        let owned: Vec<String> = ["abcdefgh", "abcdefghij", "abcdefgh", "abcdefghi", "abcdefg", "", "abcdefghijklmnop",
            "abcdefghijklmnop", "abcdefghijklmnopq", "a"].iter().map(|text| text.to_string()).collect();
        check(&owned, 3);
    }

    #[test]
    fn empty_and_single() {
        let ordered = sorter_for(&[], &[]);
        assert!(ordered.order.is_empty());
        assert!(ordered.descending().unwrap().is_empty());
        let ordered = sorter_for(&["a"], &[true]);
        assert_eq!(ordered.order, [0]);
        assert_eq!(ordered.directories, 1);
    }

    #[test]
    fn parallel_buckets_equal_the_reference() {
        let count = 70_000usize;
        let owned: Vec<String> = (0..count).map(|index| format!("{:x}n{}", index % 251, (index * 7919) % count)).collect();
        check(&owned, 1000);
    }

    #[test]
    fn buckets_follow_the_bytes_all_keys_share() {
        // Keys sharing 6 leading bytes (zero padding), 7, and all 8 of the first chunk.
        for stem in ["", "frame_", "a stem longer than a chunk "] {
            let owned: Vec<String> = (0..20_000usize).map(|index| format!("{stem}{}", (index * 7919) % 30_000)).collect();
            check(&owned, usize::MAX);
        }
    }

    /// cargo test --release bench_name_shapes -- --ignored --nocapture
    #[test]
    #[ignore]
    fn bench_name_shapes() {
        let shapes: [(&str, fn(usize) -> String); 6] = [
            ("one stem", |index| format!("frame_{:06}.png", index)),
            ("two stems", |index| format!("{}_{:06}.jpg", if index % 2 == 0 { "IMG" } else { "VID" }, index)),
            ("dated", |index| format!("IMG_2024{:04}_{:06}.jpg", index % 1231, index.wrapping_mul(7919) % 1_000_000)),
            ("diverse", |index| format!("{:08x}_{}.txt", index.wrapping_mul(2_654_435_761) as u32, index)),
            ("numbered", |index| format!("{}.jpg", index.wrapping_mul(7919) % 1_000_000)),
            ("short stem", |index| format!("IMG_{}.jpg", index.wrapping_mul(7919) % 1_000_000)),
        ];
        for (label, name) in shapes {
            let mut scratch = Scratch::default();
            let mut builders = [Sorter::default()];
            for index in 0..200_000 / SEG {
                builders[0].add(index, &[0u8; SEG], |local, bytes| {
                    let points: Vec<u32> = name((index << SEG_SHIFT) + local).chars().map(|c| c as u32).collect();
                    code_points(&points, &mut scratch, &mut Wtf8(bytes));
                    Ok::<(), Failure>(())
                }).unwrap();
            }
            for threads in [1, 8] {
                let started = std::time::Instant::now();
                let ordered = Sorter::finish(&builders, threads).unwrap();
                eprintln!("{label}: {} entries on {threads} threads: {:.1} ms", ordered.order.len(),
                    started.elapsed().as_secs_f64() * 1e3);
            }
        }
    }
}
