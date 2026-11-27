//! The scan pipeline's native side: the shared state, the enumerator thread
//! (E) and the key thread (K). Neither touches Python; the calling thread (P,
//! python.rs) creates the `Listing` objects from the segments they publish.

use crate::keys::{self, Scratch, Wtf8};
use crate::record::{self, Record, EPOCH};
use crate::segment::{Name, Segment, Table, Values};
use crate::sort::{Ordered, Sorter};
use crate::win::*;
use crate::Failure;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::mpsc::{sync_channel, Receiver, SyncSender};
use std::sync::{Arc, Condvar, Mutex, MutexGuard};
use std::time::{Duration, Instant};

/// Bytes per kernel call, below 64 KiB. While a folder's files have recently
/// been created, read or opened, a call with 64 KiB or more costs 1.4 to 2.4
/// times as much per record and a smaller call does not: 120,000 new entries
/// took 23 ms at 60 KiB and 50 ms at 256 KiB, 200,000 just read ones 47 ms and
/// 64 ms. Only for a folder whose files nothing has used for a while is 256 KiB
/// faster, by 5 to 8% (200,000 entries: 43 ms against 47 ms). Windows 11 26300,
/// NTFS, 2026-11-26. ReFS shows no step: 200,000 entries on a hard disk took
/// 99 ms at 60 KiB, 98 ms at 64 KiB and 95 ms at 256 KiB (2026-11-27).
const BUFFER_BYTES: usize = 60 << 10;
/// Batches `open` reads on the calling thread: four with entries (240 KiB,
/// about one batch of the 256 KiB buffer before) and the call that ends the
/// folder. A longer folder keeps their five buffers in flight between the
/// reader and the decoder.
const INLINE_BATCHES: usize = 5;

pub struct Request {
    /// The `\\?\` path of the folder, NUL-terminated.
    pub path: Vec<u16>,
    /// `os.path.join(path, '')` of the caller's path: link targets are opened as
    /// `os.stat(os.path.join(path, name))` opens them.
    pub join_prefix: Vec<u16>,
    pub link_tags: Vec<u32>,
    /// The table of this location's previous listing, for unchanged-refresh detection.
    pub previous: Option<Arc<Table>>,
}

#[derive(Default)]
pub struct State {
    pub segments: Vec<Arc<Segment>>,
    pub scope: Option<(u64, [u8; 16])>,
    /// First entry that differs from the previous table; Some(0) without one.
    pub difference: Option<usize>,
    /// The enumerator's outcome, once it has stopped.
    pub enumerated: Option<Result<(), Failure>>,
    /// The key thread's outcome: Ok(None) when the folder is unchanged.
    pub ordered: Option<Result<Option<Ordered>, Failure>>,
}

#[derive(Default)]
pub struct Shared {
    state: Mutex<State>,
    changed: Condvar,
    cancel: AtomicBool,
}

impl Shared {
    pub fn lock(&self) -> MutexGuard<'_, State> {
        self.state.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    fn update(&self, change: impl FnOnce(&mut State)) {
        change(&mut self.lock());
        self.changed.notify_all();
    }

    pub fn canceled(&self) -> bool {
        self.cancel.load(Ordering::Relaxed)
    }

    pub fn cancel(&self) {
        self.cancel.store(true, Ordering::Relaxed);
        self.update(|_| {});
    }

    /// Waits until `ready` holds, cancellation, or `timeout` (None: no limit).
    pub fn wait<T>(&self, timeout: Option<Duration>, ready: impl Fn(&State) -> bool,
        take: impl FnOnce(&State) -> T) -> T {
        let deadline = timeout.map(|timeout| Instant::now() + timeout);
        let mut state = self.lock();
        while !ready(&state) && !self.canceled() {
            state = match deadline {
                None => self.changed.wait(state).unwrap_or_else(|poisoned| poisoned.into_inner()),
                Some(deadline) => {
                    let now = Instant::now();
                    if now >= deadline {
                        break;
                    }
                    self.changed.wait_timeout(state, deadline - now)
                        .unwrap_or_else(|poisoned| poisoned.into_inner()).0
                }
            };
        }
        take(&state)
    }
}

fn panic_message(payload: Box<dyn std::any::Any + Send>) -> String {
    payload.downcast_ref::<&str>().map(|text| text.to_string())
        .or_else(|| payload.downcast_ref::<String>().cloned())
        .unwrap_or_else(|| "panic".to_string())
}

pub fn guarded<T>(work: impl FnOnce() -> Result<T, Failure>) -> Result<T, Failure> {
    catch_unwind(AssertUnwindSafe(work)).unwrap_or_else(|payload| Err(Failure::Panic(panic_message(payload))))
}

// ---- E: enumeration ----

/// (volume serial, directory file ID), or None outside native NTFS/ReFS
/// scope: UNC, another file system, no open-by-file-ID support, or a final
/// path too long to check.
fn volume_scope(handle: &OwnedHandle) -> Result<Option<(u64, [u8; 16])>, Failure> {
    let mut path = vec![0u16; 32768];
    let length = unsafe { GetFinalPathNameByHandleW(handle.0, path.as_mut_ptr(), path.len() as u32, 0) } as usize;
    if length == 0 {
        return Err(Failure::Win32(last_error()));
    }
    // Python: path.upper().startswith('\\\\?\\UNC\\')
    let upper = |unit: u16| if (b'a' as u16..=b'z' as u16).contains(&unit) { unit - 32 } else { unit };
    let unc = path[..length.min(path.len())].iter().map(|&unit| upper(unit)).take(8).eq("\\\\?\\UNC\\".encode_utf16());
    if length >= path.len() || unc {
        return Ok(None);
    }
    let mut flags = 0u32;
    let mut file_system = [0u16; 32];
    let ok = unsafe {
        GetVolumeInformationByHandleW(handle.0, std::ptr::null_mut(), 0, std::ptr::null_mut(),
            std::ptr::null_mut(), &mut flags, file_system.as_mut_ptr(), file_system.len() as u32)
    };
    if ok == 0 {
        return Err(Failure::Win32(last_error()));
    }
    let name_length = file_system.iter().position(|&unit| unit == 0).unwrap_or(file_system.len());
    let name = &file_system[..name_length];
    let native = name == "NTFS".encode_utf16().collect::<Vec<_>>().as_slice()
        || name == "ReFS".encode_utf16().collect::<Vec<_>>().as_slice();
    if !native || flags & FILE_SUPPORTS_OPEN_BY_FILE_ID == 0 {
        return Ok(None);
    }
    let mut data = [0u64; 3];
    let ok = unsafe { GetFileInformationByHandleEx(handle.0, FILE_ID_INFO, data.as_mut_ptr().cast(), 24) };
    if ok == 0 {
        return Err(Failure::Win32(last_error()));
    }
    let mut identity = [0u8; 16];
    identity[..8].copy_from_slice(&data[1].to_le_bytes());
    identity[8..].copy_from_slice(&data[2].to_le_bytes());
    Ok(Some((data[0], identity)))
}

/// Replaces `is_dir`, size and modification time with the link target's, as
/// `os.stat` (following links) reports them; where `os.stat` raises, the entry
/// keeps its own. The branches are CPython's `win32_xstat_slow_impl`.
fn follow_link(prefix: &[u16], record: &Record<'_>, path: &mut Vec<u16>, values: &mut Values) {
    // ntpath.join would treat a leading "X:" as a drive; NTFS names cannot hold ':'.
    if record.units().nth(1) == Some(b':' as u16) {
        return;
    }
    path.clear();
    path.extend_from_slice(prefix);
    path.extend(record.units());
    path.push(0);
    let handle = match OwnedHandle::open(path, FILE_READ_ATTRIBUTES, 0, BACKUP_SEMANTICS) {
        Ok(handle) => handle,
        // A console device needs read access.
        Err(ERROR_INVALID_PARAMETER) => match OwnedHandle::open(path, FILE_READ_ATTRIBUTES | GENERIC_READ,
            SHARE_READ_WRITE, BACKUP_SEMANTICS) {
            Ok(handle) => handle,
            Err(_) => return,
        },
        Err(_) => return,
    };
    let kind = unsafe { GetFileType(handle.0) };
    if kind != FILE_TYPE_DISK {
        if kind == FILE_TYPE_UNKNOWN && last_error() != 0 {
            return;
        }
        let attributes = unsafe { GetFileAttributesW(path.as_ptr()) };
        values.is_dir = attributes != INVALID_FILE_ATTRIBUTES && attributes & FILE_ATTRIBUTE_DIRECTORY != 0;
        values.size = 0;
        values.modified = EPOCH;
        return;
    }
    let mut information = ByHandleFileInformation::default();
    let mut basic = FileBasicInfo::default();
    let ok = unsafe {
        GetFileInformationByHandle(handle.0, &mut information) != 0
            && GetFileInformationByHandleEx(handle.0, FILE_BASIC_INFO, (&mut basic as *mut FileBasicInfo).cast(),
                std::mem::size_of::<FileBasicInfo>() as u32) != 0
    };
    if ok {
        values.is_dir = information.attributes & FILE_ATTRIBUTE_DIRECTORY != 0;
        values.size = (information.size_high as u64) << 32 | information.size_low as u64;
        values.modified = basic.write;
    } else if matches!(last_error(), ERROR_INVALID_FUNCTION | ERROR_INVALID_PARAMETER | ERROR_NOT_SUPPORTED) {
        // A volume or disk: os.stat reports a zeroed block device.
        values.is_dir = false;
        values.size = 0;
        values.modified = EPOCH;
    }
}

/// A kernel call's result, as the reader hands it to the decoder.
enum Batch {
    Data(Box<[u64]>),
    End,
    Error(Failure),
}

/// A zero-filled kernel buffer.
fn new_buffer() -> Result<Box<[u64]>, Failure> {
    let mut buffer = Vec::new();
    buffer.try_reserve_exact(BUFFER_BYTES / 8).map_err(|_| Failure::Memory)?;
    buffer.resize(BUFFER_BYTES / 8, 0u64);
    Ok(buffer.into_boxed_slice())
}

/// One kernel call into a zero-filled buffer.
fn read_batch(handle: &OwnedHandle, class: i32, mut buffer: Box<[u64]>) -> Batch {
    let ok = unsafe { GetFileInformationByHandleEx(handle.0, class, buffer.as_mut_ptr().cast(), BUFFER_BYTES as u32) };
    if ok != 0 {
        return Batch::Data(buffer);
    }
    match last_error() {
        ERROR_NO_MORE_FILES => Batch::End,
        // The first call reports a folder without any entry this way. Only a
        // volume root can be one: it has no `.` and `..` (os.listdir treats
        // FindFirstFileW's ERROR_FILE_NOT_FOUND the same).
        ERROR_FILE_NOT_FOUND if class == FILE_ID_EXTD_DIRECTORY_RESTART_INFO => Batch::End,
        error => Batch::Error(Failure::Win32(error)),
    }
}

/// A folder `open` has opened: its handle, scope and first batches.
pub struct Opened {
    handle: OwnedHandle,
    scope: (u64, [u8; 16]),
    batches: Vec<Batch>,
}

impl Opened {
    /// The batches read so far end the folder: its last batch or an error.
    pub fn complete(&self) -> bool {
        matches!(self.batches.last(), Some(Batch::End | Batch::Error(_)))
    }
}

/// Opens the folder, checks its scope and reads up to `INLINE_BATCHES` on the
/// calling thread: a folder that ends within them needs no other thread
/// (0.26 ms against 0.51 ms for 500 entries).
/// Unsupported: outside the native scope.
pub fn open(request: &Request) -> Result<Opened, Failure> {
    let handle = OwnedHandle::open(&request.path, FILE_LIST_DIRECTORY_READ_ATTRIBUTES, SHARE_ALL, BACKUP_SEMANTICS)
        .map_err(Failure::Win32)?;
    let scope = volume_scope(&handle)?.ok_or(Failure::Unsupported)?;
    let mut opened = Opened { handle, scope, batches: Vec::new() };
    let mut class = FILE_ID_EXTD_DIRECTORY_RESTART_INFO;
    while !opened.complete() && opened.batches.len() < INLINE_BATCHES {
        let batch = read_batch(&opened.handle, class, new_buffer()?);
        opened.batches.push(batch);
        class = FILE_ID_EXTD_DIRECTORY_INFO;
    }
    Ok(opened)
}

/// The reader thread: continues an opened folder's kernel calls, so the next
/// batch is read while the previous one is decoded. It reuses the buffers
/// `open` created; the decoder returns them zero-filled, as the reference
/// scanner's were.
fn read_batches(handle: &OwnedHandle, free: Receiver<Box<[u64]>>, full: SyncSender<Batch>, shared: &Shared,
    stop: &AtomicBool) {
    // No buffer arrives once the decoder has stopped.
    while let Ok(buffer) = free.recv() {
        if stop.load(Ordering::Relaxed) || shared.canceled() {
            return;
        }
        let batch = read_batch(handle, FILE_ID_EXTD_DIRECTORY_INFO, buffer);
        let last = !matches!(batch, Batch::Data(_));
        if full.send(batch).is_err() || last {
            return;
        }
    }
}

/// E: decodes an opened folder's batches, with a reader thread for the rest
/// when there is more, and publishes the outcome.
pub fn enumerate(shared: &Shared, request: &Request, opened: Opened) {
    let outcome = guarded(|| enumerate_opened(shared, request, opened));
    shared.update(|state| state.enumerated = Some(outcome));
}

fn enumerate_opened(shared: &Shared, request: &Request, opened: Opened) -> Result<(), Failure> {
    let complete = opened.complete();
    let Opened { handle, scope, batches: first } = opened;
    let previous = request.previous.as_deref().filter(|table| table.scope == scope);
    shared.update(|state| {
        state.scope = Some(scope);
        if previous.is_none() {
            state.difference = Some(0);
        }
    });
    // Room for every buffer: neither thread waits to hand one over.
    let (free_sender, free) = sync_channel::<Box<[u64]>>(INLINE_BATCHES);
    let (full, batches) = sync_channel::<Batch>(INLINE_BATCHES);
    let stop = AtomicBool::new(false);
    std::thread::scope(|scope| {
        if complete {
            drop(full);
        } else {
            let (handle, stop) = (&handle, &stop);
            std::thread::Builder::new().name("fsenum-read".into())
                .spawn_scoped(scope, move || read_batches(handle, free, full, shared, stop))
                .map_err(|error| Failure::Thread(error.to_string()))?;
        }
        let outcome = decode_batches(shared, request, previous, first.into_iter().chain(batches), free_sender);
        // The reader stops at its next buffer; the scope waits for it.
        stop.store(true, Ordering::Relaxed);
        outcome
    })
}

/// The decoder: validates records, follows links, compares with the previous
/// table and publishes full segments.
fn decode_batches(shared: &Shared, request: &Request, mut previous: Option<&Table>,
    mut batches: impl Iterator<Item = Batch>, free: SyncSender<Box<[u64]>>) -> Result<(), Failure> {
    let mut segment = Segment::new()?;
    let mut count = 0usize;
    let mut link_path = Vec::new();
    loop {
        let mut buffer = match batches.next() {
            Some(Batch::Data(buffer)) => buffer,
            Some(Batch::End) => break,
            Some(Batch::Error(failure)) => return Err(failure),
            None => return Err(if shared.canceled() { Failure::Canceled } else {
                Failure::Panic("the directory reader stopped".into())
            }),
        };
        let data = unsafe { std::slice::from_raw_parts(buffer.as_ptr().cast::<u8>(), BUFFER_BYTES) };
        record::for_each(data, |record| -> Result<(), Failure> {
            let mut values = Values {
                is_dir: record.attributes & FILE_ATTRIBUTE_DIRECTORY != 0,
                size: record.size as u64,
                modified: record.modified,
                created: record.created,
                attributes: record.attributes,
                identity: *record.identity,
            };
            if record.attributes & FILE_ATTRIBUTE_REPARSE_POINT != 0 && request.link_tags.contains(&record.tag) {
                if shared.canceled() {
                    return Err(Failure::Canceled);
                }
                follow_link(&request.join_prefix, &record, &mut link_path, &mut values);
            }
            if let Some(table) = previous {
                let same = count < table.count && {
                    let (old, local) = table.segment(count);
                    old.equals(local, &record, &values)
                };
                if !same {
                    previous = None;
                    shared.update(|state| state.difference = Some(count));
                }
            }
            if count == u32::MAX as usize {
                return Err(Failure::Memory);
            }
            segment.push(&record, &values)?;
            count += 1;
            if segment.is_full() {
                let full = std::mem::replace(&mut segment, Segment::new()?);
                shared.update(|state| state.segments.push(Arc::new(full)));
            }
            Ok(())
        })?;
        buffer.fill(0);
        let _ = free.send(buffer);
        if shared.canceled() {
            return Err(Failure::Canceled);
        }
    }
    shared.update(|state| {
        if segment.len() > 0 {
            state.segments.push(Arc::new(std::mem::take(&mut segment)));
        }
        if let Some(table) = previous {
            if table.count != count {
                state.difference = Some(count.min(table.count));
            }
        }
    });
    Ok(())
}

// ---- K: natural keys and order ----

/// Appends the natural key of the segment's entry `local`. A name unit yields
/// at most 7 key bytes (a lone digit becomes "000000d"), so both paths
/// reserve before they write.
pub fn append_key(segment: &Segment, local: usize, scratch: &mut Scratch, bytes: &mut Vec<u8>) -> Result<(), Failure> {
    match segment.name(local) {
        Name::Latin1(name) => keys::latin1_wtf8(name, bytes),
        Name::Utf16(name) => {
            bytes.try_reserve(name.len() / 2 * 7 + 8).map_err(|_| Failure::Memory)?;
            keys::utf16(name.chunks_exact(2).map(|pair| u16::from_le_bytes([pair[0], pair[1]])), scratch,
                &mut Wtf8(bytes));
            Ok(())
        }
    }
}

/// Threads for the final sort: it runs only after the last batch, for a few
/// milliseconds, so it may use more cores than the steady pipeline.
pub fn threads() -> usize {
    std::thread::available_parallelism().map_or(1, |count| count.get()).min(8)
}

/// Key builders, the K thread included. Keys take about as much CPU time as
/// the kernel enumeration; two builders finish with E, so the sort is the
/// only tail.
const KEY_BUILDERS: usize = 2;

pub fn order(shared: &Shared) {
    let mut builders = Vec::new();
    let outcome = guarded(|| order_entries(shared, &mut builders));
    shared.update(|state| state.ordered = Some(outcome));
    // The keys are freed once the order is out: P builds its result meanwhile.
    drop(builders);
}

fn order_entries(shared: &Shared, builders: &mut Vec<Sorter>) -> Result<Option<Ordered>, Failure> {
    let claimed = AtomicUsize::new(0);
    // Helpers only while the folder is still being read: a finished one is small.
    let helpers = if shared.lock().enumerated.is_none() { KEY_BUILDERS - 1 } else { 0 };
    let built = std::thread::scope(|scope| {
        // A helper that cannot start leaves its segments to the others.
        let helpers: Vec<_> = (0..helpers).filter_map(|_| std::thread::Builder::new()
            .name("fsenum-keys".into())
            .spawn_scoped(scope, || guarded(|| build_keys(shared, &claimed))).ok()).collect();
        let mut built = vec![build_keys(shared, &claimed)];
        built.extend(helpers.into_iter()
            .map(|helper| helper.join().unwrap_or_else(|_| Err(Failure::Panic("key thread panicked".into())))));
        built
    });
    for sorter in built {
        // None from one builder means every builder saw the folder unchanged.
        let Some(sorter) = sorter? else { return Ok(None) };
        builders.push(sorter);
    }
    Sorter::finish(builders, threads()).map(Some)
}

/// One key builder: claims segments in turn and adds their keys to its own
/// sorter. None: the folder is unchanged, so no keys are needed.
fn build_keys(shared: &Shared, claimed: &AtomicUsize) -> Result<Option<Sorter>, Failure> {
    let mut sorter = Sorter::default();
    let mut scratch = Scratch::default();
    loop {
        let index = claimed.fetch_add(1, Ordering::Relaxed);
        let (segment, unchanged) = shared.wait(None,
            |state| state.enumerated.is_some() || (state.difference.is_some() && state.segments.len() > index),
            |state| (state.difference.and_then(|_| state.segments.get(index).cloned()),
                matches!(state.enumerated, Some(Ok(()))) && state.difference.is_none()));
        if shared.canceled() || matches!(shared.lock().enumerated, Some(Err(_))) {
            return Err(Failure::Canceled);
        }
        if unchanged {
            return Ok(None);
        }
        // Without a segment the enumeration has finished and every segment is claimed.
        let Some(segment) = segment else { return Ok(Some(sorter)) };
        sorter.add(index, &segment.is_dir, |local, bytes| append_key(&segment, local, &mut scratch, bytes))?;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn wide(text: &str) -> Vec<u16> {
        text.encode_utf16().chain(std::iter::once(0)).collect()
    }

    fn run(path: &std::path::Path, previous: Option<Arc<Table>>) -> (Shared, Result<(), Failure>) {
        let shared = Shared::default();
        let text = format!("\\\\?\\{}", path.display());
        let request = Request {
            path: wide(&text),
            join_prefix: format!("{}\\", path.display()).encode_utf16().collect(),
            link_tags: vec![0xA000_0003, 0xA000_000C],
            previous,
        };
        let opened = match open(&request) {
            Ok(opened) => opened,
            Err(failure) => return (shared, Err(failure)),
        };
        std::thread::scope(|scope| {
            scope.spawn(|| enumerate(&shared, &request, opened));
            scope.spawn(|| order(&shared));
        });
        let outcome = shared.lock().enumerated.take().unwrap();
        (shared, outcome)
    }

    fn table(shared: &Shared) -> Arc<Table> {
        let mut state = shared.lock();
        let segments = state.segments.clone();
        Arc::new(Table {
            count: segments.iter().map(|segment| segment.len()).sum(),
            segments,
            scope: state.scope.unwrap(),
            ordered: state.ordered.take().unwrap().unwrap().unwrap(),
        })
    }

    #[test]
    fn enumerates_a_temporary_folder_and_detects_changes() {
        let folder = std::env::temp_dir().join(format!("fsenum-test-{}", std::process::id()));
        std::fs::create_dir_all(&folder).unwrap();
        for index in 0..5000 {
            std::fs::write(folder.join(format!("file{index}.txt")), b"x").unwrap();
        }
        std::fs::create_dir_all(folder.join("sub")).unwrap();
        let (shared, outcome) = run(&folder, None);
        if let Err(Failure::Unsupported) = outcome {
            std::fs::remove_dir_all(&folder).unwrap();
            return;
        }
        outcome.unwrap();
        let first = table(&shared);
        assert_eq!(first.count, 5001);
        assert_eq!(first.ordered.directories, 1);
        let (shared, outcome) = run(&folder, Some(first.clone()));
        outcome.unwrap();
        assert!(shared.lock().difference.is_none());
        assert!(matches!(shared.lock().ordered, Some(Ok(None))));
        std::fs::write(folder.join("file2500.txt"), b"changed").unwrap();
        let (shared, outcome) = run(&folder, Some(first));
        outcome.unwrap();
        assert!(shared.lock().difference.is_some());
        std::fs::remove_dir_all(&folder).unwrap();
    }

    #[test]
    fn missing_folder_is_a_win32_error() {
        let (_, outcome) = run(&std::env::temp_dir().join("fsenum-missing-folder-x"), None);
        assert!(matches!(outcome, Err(Failure::Win32(2 | 3))));
    }

    /// FSENUM_BENCH=<folder> cargo test --release -- --ignored --nocapture
    #[test]
    #[ignore]
    fn bench_keys_and_sort() {
        let Some(folder) = std::env::var_os("FSENUM_BENCH") else { return };
        let (shared, outcome) = run(std::path::Path::new(&folder), None);
        outcome.unwrap();
        let segments = shared.lock().segments.clone();
        for _ in 0..3 {
            let started = Instant::now();
            let mut scratch = Scratch::default();
            let mut builders = [Sorter::default()];
            for (index, segment) in segments.iter().enumerate() {
                builders[0].add(index, &segment.is_dir, |local, bytes| append_key(segment, local, &mut scratch, bytes))
                    .unwrap();
            }
            let keyed = started.elapsed();
            let ordered = Sorter::finish(&builders, threads()).unwrap();
            let sorted = started.elapsed() - keyed;
            drop(builders);
            eprintln!("keys {:.1} ms; sort {:.1} ms; free {:.1} ms; {} entries", keyed.as_secs_f64() * 1e3,
                sorted.as_secs_f64() * 1e3, (started.elapsed() - keyed - sorted).as_secs_f64() * 1e3,
                ordered.order.len());
        }
    }
}
