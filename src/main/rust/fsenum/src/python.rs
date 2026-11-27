//! The CPython side (limited API, python3.dll): the calling thread of a scan
//! (P) and the module functions. Every exported function runs under
//! `boundary`, which turns a Rust panic into RuntimeError, because PyO3-style
//! PanicException (a BaseException) would bypass the scan workers' handlers.
//!
//! P holds the GIL only to create objects, at most BUDGET at a time, then
//! releases it and sleeps briefly so the Qt thread can paint: a bare release
//! does not hand the GIL over (Done/FSPaneArch002.md R04, LatestJobs).

#![allow(non_snake_case, non_camel_case_types, clippy::missing_safety_doc)]

use crate::keys::{self, Points, Scratch, Wtf8};
use crate::pipeline::{self, Request, Shared};
use crate::record::{self, filetime_ns, HEADER};
use crate::segment::{Name, Segment, Table, Values, SEG, SEG_SHIFT};
use crate::sort::Sorter;
use crate::win::{format_message, FILE_ATTRIBUTE_DIRECTORY, FILE_ATTRIBUTE_REPARSE_POINT};
use crate::Failure;
use std::ffi::{c_char, c_int, c_long, c_ulong, c_void, CStr};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::ptr::null_mut;
use std::sync::{Arc, OnceLock};
use std::time::{Duration, Instant};

type Py_ssize_t = isize;

#[repr(C)]
pub struct PyObject {
    _private: [u8; 0],
}

#[repr(C)]
pub struct PyThreadState {
    _private: [u8; 0],
}

#[repr(C)]
struct PyMethodDef {
    name: *const c_char,
    method: *const c_void,
    flags: c_int,
    doc: *const c_char,
}

unsafe impl Sync for PyMethodDef {}

#[repr(C)]
struct PyModuleDefBase {
    refcount: Py_ssize_t,
    kind: *mut c_void,
    init: *const c_void,
    index: Py_ssize_t,
    copy: *mut PyObject,
}

#[repr(C)]
struct PyModuleDef {
    base: PyModuleDefBase,
    name: *const c_char,
    doc: *const c_char,
    size: Py_ssize_t,
    methods: *const PyMethodDef,
    slots: *mut c_void,
    traverse: *mut c_void,
    clear: *mut c_void,
    free: *mut c_void,
}

#[repr(C)]
struct Py_buffer {
    buf: *mut c_void,
    obj: *mut PyObject,
    len: Py_ssize_t,
    itemsize: Py_ssize_t,
    readonly: c_int,
    ndim: c_int,
    format: *mut c_char,
    shape: *mut Py_ssize_t,
    strides: *mut Py_ssize_t,
    suboffsets: *mut Py_ssize_t,
    internal: *mut c_void,
}

type Destructor = unsafe extern "C" fn(*mut PyObject);

#[link(name = "python3", kind = "raw-dylib")]
unsafe extern "C" {
    fn PyModule_Create2(definition: *mut PyModuleDef, api: c_int) -> *mut PyObject;
    fn PyModule_AddObjectRef(module: *mut PyObject, name: *const c_char, value: *mut PyObject) -> c_int;
    fn PyModule_AddIntConstant(module: *mut PyObject, name: *const c_char, value: c_long) -> c_int;
    fn PyImport_ImportModule(name: *const c_char) -> *mut PyObject;
    fn PyObject_GetAttrString(object: *mut PyObject, name: *const c_char) -> *mut PyObject;
    fn PyObject_CallNoArgs(callable: *mut PyObject) -> *mut PyObject;
    fn PyObject_CallObject(callable: *mut PyObject, arguments: *mut PyObject) -> *mut PyObject;
    fn PyObject_IsTrue(object: *mut PyObject) -> c_int;
    fn PyObject_Type(object: *mut PyObject) -> *mut PyObject;
    fn PyCallable_Check(object: *mut PyObject) -> c_int;
    fn PyObject_GetBuffer(object: *mut PyObject, view: *mut Py_buffer, flags: c_int) -> c_int;
    fn PyBuffer_Release(view: *mut Py_buffer);
    fn Py_IncRef(object: *mut PyObject);
    fn Py_DecRef(object: *mut PyObject);
    fn Py_BuildValue(format: *const c_char, ...) -> *mut PyObject;
    fn PyErr_SetString(kind: *mut PyObject, message: *const c_char);
    fn PyErr_SetObject(kind: *mut PyObject, value: *mut PyObject);
    fn PyErr_NoMemory() -> *mut PyObject;
    fn PyErr_Occurred() -> *mut PyObject;
    fn PyErr_Clear();
    fn PyErr_GetRaisedException() -> *mut PyObject;
    fn PyErr_SetRaisedException(exception: *mut PyObject);
    fn PyEval_SaveThread() -> *mut PyThreadState;
    fn PyEval_RestoreThread(state: *mut PyThreadState);
    fn PyLong_FromLongLong(value: i64) -> *mut PyObject;
    fn PyLong_FromUnsignedLongLong(value: u64) -> *mut PyObject;
    fn PyLong_FromString(text: *const c_char, end: *mut *mut c_char, base: c_int) -> *mut PyObject;
    fn PyLong_AsUnsignedLong(object: *mut PyObject) -> c_ulong;
    fn PyBool_FromLong(value: c_long) -> *mut PyObject;
    fn PyUnicode_DecodeLatin1(text: *const c_char, size: Py_ssize_t, errors: *const c_char) -> *mut PyObject;
    fn PyUnicode_DecodeUTF16(text: *const c_char, size: Py_ssize_t, errors: *const c_char,
        byte_order: *mut c_int) -> *mut PyObject;
    fn PyUnicode_DecodeUTF32(text: *const c_char, size: Py_ssize_t, errors: *const c_char,
        byte_order: *mut c_int) -> *mut PyObject;
    fn PyUnicode_FromWideChar(text: *const u16, size: Py_ssize_t) -> *mut PyObject;
    fn PyUnicode_FromString(text: *const c_char) -> *mut PyObject;
    fn PyUnicode_AsWideCharString(object: *mut PyObject, size: *mut Py_ssize_t) -> *mut u16;
    fn PyUnicode_AsUCS4(object: *mut PyObject, buffer: *mut u32, length: Py_ssize_t, copy_null: c_int) -> *mut u32;
    fn PyUnicode_GetLength(object: *mut PyObject) -> Py_ssize_t;
    fn PyMem_Free(memory: *mut c_void);
    fn PyBytes_FromStringAndSize(text: *const c_char, size: Py_ssize_t) -> *mut PyObject;
    fn PyBytes_AsString(object: *mut PyObject) -> *mut c_char;
    fn PyBytes_AsStringAndSize(object: *mut PyObject, buffer: *mut *mut c_char, length: *mut Py_ssize_t) -> c_int;
    fn PyTuple_New(size: Py_ssize_t) -> *mut PyObject;
    fn PyTuple_SetItem(tuple: *mut PyObject, index: Py_ssize_t, item: *mut PyObject) -> c_int;
    fn PyObject_GC_UnTrack(object: *mut c_void);
    fn PyTuple_GetItem(tuple: *mut PyObject, index: Py_ssize_t) -> *mut PyObject;
    fn PyTuple_Size(tuple: *mut PyObject) -> Py_ssize_t;
    fn PySequence_Tuple(object: *mut PyObject) -> *mut PyObject;
    fn PyCapsule_New(pointer: *mut c_void, name: *const c_char, destructor: Option<Destructor>) -> *mut PyObject;
    fn PyCapsule_GetPointer(capsule: *mut PyObject, name: *const c_char) -> *mut c_void;
    fn PyCapsule_IsValid(capsule: *mut PyObject, name: *const c_char) -> c_int;
}

/// Longest GIL hold while creating or releasing objects; then the GIL is handed to Qt.
const BUDGET: Duration = Duration::from_millis(4);
const HAND_OVER: Duration = Duration::from_millis(1);
/// P wakes at least this often to call `check_canceled`.
const WAKE: Duration = Duration::from_millis(10);
/// Win32 errors that send the caller to its fallback scanner, as before.
const UNSUPPORTED: [u32; 5] = [1, 50, 87, 120, 124];
const CAPSULE: &CStr = c"_fsenum.Table";

struct Globals {
    none: *mut PyObject,
    value_error: *mut PyObject,
    type_error: *mut PyObject,
    runtime_error: *mut PyObject,
    os_error: *mut PyObject,
}

unsafe impl Send for Globals {}
unsafe impl Sync for Globals {}

static GLOBALS: OnceLock<Globals> = OnceLock::new();

fn globals() -> &'static Globals {
    GLOBALS.get().expect("_fsenum is initialized")
}

enum Error {
    /// A Python exception is already set.
    Python,
    Failure(Failure),
    Type(&'static CStr),
    Value(&'static CStr),
}

impl From<Failure> for Error {
    fn from(failure: Failure) -> Error {
        Error::Failure(failure)
    }
}

type Result<T> = std::result::Result<T, Error>;

unsafe fn object(pointer: *mut PyObject) -> Result<*mut PyObject> {
    if pointer.is_null() { Err(Error::Python) } else { Ok(pointer) }
}

/// A strong reference released on drop (with the GIL held).
struct Owned(*mut PyObject);

impl Owned {
    unsafe fn new(pointer: *mut PyObject) -> Result<Owned> {
        unsafe { object(pointer).map(Owned) }
    }
    fn into_raw(self) -> *mut PyObject {
        let pointer = self.0;
        std::mem::forget(self);
        pointer
    }
}

impl Drop for Owned {
    fn drop(&mut self) {
        unsafe { Py_DecRef(self.0) }
    }
}

unsafe fn new_none() -> *mut PyObject {
    let none = globals().none;
    unsafe { Py_IncRef(none) };
    none
}

unsafe fn raise(error: Error) {
    let globals = globals();
    unsafe {
        match error {
            Error::Python => {}
            Error::Type(message) => PyErr_SetString(globals.type_error, message.as_ptr()),
            Error::Value(message) => PyErr_SetString(globals.value_error, message.as_ptr()),
            Error::Failure(Failure::Memory) => {
                PyErr_NoMemory();
            }
            Error::Failure(Failure::Record(error)) => {
                let message = std::ffi::CString::new(error.message()).unwrap();
                PyErr_SetString(globals.value_error, message.as_ptr());
            }
            Error::Failure(Failure::Win32(code)) => raise_os_error(code),
            Error::Failure(Failure::Thread(message)) => runtime_error(&format!("can't start new thread: {message}")),
            Error::Failure(Failure::Panic(message)) => runtime_error(&format!("_fsenum internal error: {message}")),
            Error::Failure(Failure::Unsupported | Failure::Canceled) => runtime_error("_fsenum: work stopped"),
        }
    }
}

unsafe fn runtime_error(message: &str) {
    let message = std::ffi::CString::new(message.replace('\0', " ")).unwrap();
    unsafe { PyErr_SetString(globals().runtime_error, message.as_ptr()) };
}

/// OSError(None, FormatError(code), None, code), as ctypes.WinError(code) raises.
unsafe fn raise_os_error(code: u32) {
    unsafe {
        let text = format_message(code);
        let result = (|| -> Result<()> {
            let arguments = Owned::new(PyTuple_New(4))?;
            PyTuple_SetItem(arguments.0, 0, new_none());
            PyTuple_SetItem(arguments.0, 1, object(PyUnicode_FromWideChar(text.as_ptr(), text.len() as Py_ssize_t))?);
            PyTuple_SetItem(arguments.0, 2, new_none());
            PyTuple_SetItem(arguments.0, 3, object(PyLong_FromUnsignedLongLong(code as u64))?);
            let error = Owned::new(PyObject_CallObject(globals().os_error, arguments.0))?;
            let kind = Owned::new(PyObject_Type(error.0))?;
            PyErr_SetObject(kind.0, error.0);
            Ok(())
        })();
        if result.is_err() && PyErr_Occurred().is_null() {
            PyErr_NoMemory();
        }
    }
}

fn boundary(work: impl FnOnce() -> Result<*mut PyObject>) -> *mut PyObject {
    match catch_unwind(AssertUnwindSafe(work)) {
        Ok(Ok(result)) => result,
        Ok(Err(error)) => {
            unsafe { raise(error) };
            null_mut()
        }
        Err(payload) => {
            let message = payload.downcast_ref::<&str>().map(|text| text.to_string())
                .or_else(|| payload.downcast_ref::<String>().cloned()).unwrap_or_else(|| "panic".into());
            unsafe { runtime_error(&format!("_fsenum internal error: {message}")) };
            null_mut()
        }
    }
}

/// The GIL is released while this lives and taken back on drop, also when unwinding.
struct Released(*mut PyThreadState);

impl Released {
    fn new() -> Released {
        Released(unsafe { PyEval_SaveThread() })
    }
}

impl Drop for Released {
    fn drop(&mut self) {
        unsafe { PyEval_RestoreThread(self.0) }
    }
}

/// Lets a thread waiting for the GIL (Qt) take it, then takes it back.
fn hand_over() {
    let _released = Released::new();
    std::thread::sleep(HAND_OVER);
}

unsafe fn call_check(check: *mut PyObject) -> Result<()> {
    unsafe {
        let result = object(PyObject_CallNoArgs(check))?;
        Py_DecRef(result);
    }
    Ok(())
}

fn arguments<'a, const N: usize>(args: *const *mut PyObject, count: Py_ssize_t, message: &'static CStr)
    -> Result<&'a [*mut PyObject; N]> {
    if count != N as Py_ssize_t {
        return Err(Error::Type(message));
    }
    Ok(unsafe { &*(args as *const [*mut PyObject; N]) })
}

unsafe fn wide(text: *mut PyObject, terminate: bool) -> Result<Vec<u16>> {
    unsafe {
        let mut size: Py_ssize_t = 0;
        let pointer = PyUnicode_AsWideCharString(text, &mut size);
        if pointer.is_null() {
            return Err(Error::Python);
        }
        let mut result = std::slice::from_raw_parts(pointer, size as usize).to_vec();
        PyMem_Free(pointer.cast());
        if result.contains(&0) {
            return Err(Error::Value(c"embedded null character in path"));
        }
        if terminate {
            result.push(0);
        }
        Ok(result)
    }
}

unsafe fn code_points(text: *mut PyObject, buffer: &mut Vec<u32>) -> Result<()> {
    unsafe {
        let length = PyUnicode_GetLength(text);
        if length < 0 {
            PyErr_Clear();
            return Err(Error::Type(c"names must be str"));
        }
        buffer.clear();
        buffer.resize(length as usize + 1, 0);
        if PyUnicode_AsUCS4(text, buffer.as_mut_ptr(), length + 1, 0).is_null() {
            return Err(Error::Python);
        }
        buffer.truncate(length as usize);
    }
    Ok(())
}

unsafe fn truth(value: *mut PyObject) -> Result<bool> {
    match unsafe { PyObject_IsTrue(value) } {
        -1 => Err(Error::Python),
        value => Ok(value != 0),
    }
}

unsafe fn sequence(value: *mut PyObject) -> Result<Owned> {
    unsafe { Owned::new(PySequence_Tuple(value)) }
}

unsafe fn bytes_of_u32(values: &[u32]) -> Result<*mut PyObject> {
    unsafe { object(PyBytes_FromStringAndSize(values.as_ptr().cast(), (values.len() * 4) as Py_ssize_t)) }
}

unsafe fn nanoseconds(filetime: i64) -> *mut PyObject {
    let value = filetime_ns(filetime);
    unsafe {
        match i64::try_from(value) {
            Ok(fast) => PyLong_FromLongLong(fast),
            Err(_) => {
                let text = std::ffi::CString::new(value.to_string()).unwrap();
                PyLong_FromString(text.as_ptr(), null_mut(), 10)
            }
        }
    }
}

// ---- Listing columns ----

/// One reused object per column while the raw value repeats (identical sizes
/// or timestamps are common); ints are immutable, so sharing is invisible.
struct Last {
    raw: i128,
    object: *mut PyObject,
}

impl Default for Last {
    fn default() -> Last {
        Last { raw: 0, object: null_mut() }
    }
}

impl Last {
    #[inline]
    unsafe fn get(&mut self, raw: i128, create: impl FnOnce() -> *mut PyObject) -> Result<*mut PyObject> {
        unsafe {
            if !self.object.is_null() && self.raw == raw {
                Py_IncRef(self.object);
                return Ok(self.object);
            }
            let created = object(create())?;
            self.raw = raw;
            self.object = created;
            Ok(created)
        }
    }
}

/// The six object columns of a `Listing`, as owned references.
#[derive(Default)]
struct Columns {
    columns: [Vec<*mut PyObject>; 6],
    sizes: Last,
    modified: Last,
    created: Last,
    attributes: Last,
}

impl Columns {
    fn reserve(&mut self, additional: usize) -> Result<()> {
        for column in &mut self.columns {
            column.try_reserve(additional).map_err(|_| Error::Failure(Failure::Memory))?;
        }
        Ok(())
    }

    #[inline]
    unsafe fn push_new(&mut self, segment: &Segment, local: usize) -> Result<()> {
        unsafe {
            let name = match segment.name(local) {
                Name::Latin1(bytes) => PyUnicode_DecodeLatin1(bytes.as_ptr().cast(), bytes.len() as Py_ssize_t, null_mut()),
                Name::Utf16(bytes) => {
                    let mut order: c_int = -1;
                    PyUnicode_DecodeUTF16(bytes.as_ptr().cast(), bytes.len() as Py_ssize_t, c"surrogatepass".as_ptr(), &mut order)
                }
            };
            self.columns[0].push(object(name)?);
            let values: Values = segment.values(local);
            self.columns[1].push(PyBool_FromLong(values.is_dir as c_long));
            let size = self.sizes.get(values.size as i128, || PyLong_FromUnsignedLongLong(values.size))?;
            self.columns[2].push(size);
            let modified = self.modified.get(values.modified as i128, || nanoseconds(values.modified))?;
            self.columns[3].push(modified);
            let attributes = self.attributes.get(values.attributes as i128, || PyLong_FromLongLong(values.attributes as i64))?;
            self.columns[4].push(attributes);
            let created = self.created.get(values.created as i128, || nanoseconds(values.created))?;
            self.columns[5].push(created);
        }
        Ok(())
    }

    /// Entry `index` of the previous `Listing`: the same values, shared.
    #[inline]
    unsafe fn push_previous(&mut self, previous: &Previous, index: usize) {
        for (column, tuple) in self.columns.iter_mut().zip(&previous.columns) {
            unsafe {
                let item = PyTuple_GetItem(tuple.0, index as Py_ssize_t);
                Py_IncRef(item);
                column.push(item);
            }
        }
    }

    /// Moves the references into tuples, handing the GIL over between columns.
    /// The tuples hold only `str`, `int` and `bool`, so they cannot be in a
    /// cycle: untracked, as the collector would leave them after visiting
    /// their items once (33 ms at 1,000,000 entries, in the next collection).
    unsafe fn into_tuples(&mut self, started: &mut Instant) -> Result<Tuples> {
        let mut tuples = Tuples(Vec::with_capacity(6));
        for column in &mut self.columns {
            unsafe {
                let tuple = Owned::new(PyTuple_New(column.len() as Py_ssize_t))?;
                for (index, &item) in column.iter().enumerate() {
                    PyTuple_SetItem(tuple.0, index as Py_ssize_t, item);
                }
                PyObject_GC_UnTrack(tuple.0.cast());
                column.clear();
                tuples.0.push(tuple);
            }
            if started.elapsed() > BUDGET {
                hand_over();
                *started = Instant::now();
            }
        }
        Ok(tuples)
    }
}

impl Drop for Columns {
    /// Releases what did not become tuples: cancellation or a failure.
    fn drop(&mut self) {
        unsafe {
            release_sliced(self.columns.iter().map(Vec::len), |part, index| Py_DecRef(self.columns[part][index]));
        }
    }
}

/// The six column tuples of a complete scan.
struct Tuples(Vec<Owned>);

impl Tuples {
    fn into_inner(mut self) -> Vec<Owned> {
        std::mem::take(&mut self.0)
    }
}

impl Drop for Tuples {
    /// Tuples that are not returned (cancellation while the order is awaited,
    /// a failed sort) give up their items first, so they are released like `Columns`.
    fn drop(&mut self) {
        unsafe {
            release_sliced(self.0.iter().map(|tuple| PyTuple_Size(tuple.0) as usize), |part, index| {
                PyTuple_SetItem(self.0[part].0, index as Py_ssize_t, null_mut());
            });
        }
    }
}

/// Calls `release(part, index)` for every index below each part's count, in
/// GIL-bounded slices: releasing the objects of 200,000 entries at once would
/// hold the GIL for tens of milliseconds. A pending exception stays pending.
unsafe fn release_sliced(counts: impl Iterator<Item = usize>, release: impl Fn(usize, usize)) {
    unsafe {
        let pending = PyErr_GetRaisedException();
        let mut started = Instant::now();
        for (part, count) in counts.enumerate() {
            for start in (0..count).step_by(SEG) {
                (start..(start + SEG).min(count)).for_each(|index| release(part, index));
                if started.elapsed() > BUDGET {
                    hand_over();
                    started = Instant::now();
                }
            }
        }
        if !pending.is_null() {
            PyErr_SetRaisedException(pending);
        }
    }
}

unsafe fn identities(segments: &[Arc<Segment>], count: usize) -> Result<Owned> {
    unsafe {
        let result = Owned::new(PyBytes_FromStringAndSize(std::ptr::null(), (count * 16) as Py_ssize_t))?;
        let mut target = PyBytes_AsString(result.0).cast::<u8>();
        for segment in segments {
            let length = segment.identities.len() * 16;
            std::ptr::copy_nonoverlapping(segment.identities.as_ptr().cast::<u8>(), target, length);
            target = target.add(length);
        }
        Ok(result)
    }
}

// ---- Tables ----

unsafe extern "C" fn release_table(capsule: *mut PyObject) {
    unsafe {
        let pointer = PyCapsule_GetPointer(capsule, CAPSULE.as_ptr());
        if pointer.is_null() {
            PyErr_Clear();
        } else {
            drop(Box::from_raw(pointer.cast::<Arc<Table>>()));
        }
    }
}

unsafe fn table_capsule(table: Arc<Table>) -> Result<*mut PyObject> {
    let raw = Box::into_raw(Box::new(table));
    unsafe {
        let capsule = PyCapsule_New(raw.cast(), CAPSULE.as_ptr(), Some(release_table));
        if capsule.is_null() {
            drop(Box::from_raw(raw));
            return Err(Error::Python);
        }
        Ok(capsule)
    }
}

unsafe fn table_of<'a>(capsule: *mut PyObject) -> Result<&'a Arc<Table>> {
    unsafe {
        if PyCapsule_IsValid(capsule, CAPSULE.as_ptr()) == 0 {
            return Err(Error::Type(c"expected a _fsenum table"));
        }
        Ok(&*PyCapsule_GetPointer(capsule, CAPSULE.as_ptr()).cast::<Arc<Table>>())
    }
}

/// The previous `Listing` of the location, when it can be reused.
struct Previous {
    table: Arc<Table>,
    columns: Vec<Owned>,
}

const COLUMN_NAMES: [&CStr; 6] = [c"names", c"is_dir", c"sizes", c"mtimes_ns", c"attributes", c"created_ns"];

unsafe fn previous_of(listing: *mut PyObject) -> Result<Option<Previous>> {
    unsafe {
        if listing == globals().none {
            return Ok(None);
        }
        let native = Owned::new(PyObject_GetAttrString(listing, c"_native".as_ptr()))?;
        if PyCapsule_IsValid(native.0, CAPSULE.as_ptr()) == 0 {
            return Ok(None);
        }
        let table = table_of(native.0)?.clone();
        let mut columns = Vec::with_capacity(6);
        for name in COLUMN_NAMES {
            let column = Owned::new(PyObject_GetAttrString(listing, name.as_ptr()))?;
            let size = PyTuple_Size(column.0);
            if size < 0 {
                PyErr_Clear();
                return Ok(None);
            }
            if size as usize != table.count {
                return Ok(None);
            }
            columns.push(column);
        }
        Ok(Some(Previous { table, columns }))
    }
}

// ---- scan ----

enum Materialized {
    Unchanged,
    /// Since this instant P holds the GIL.
    Complete(Instant),
}

/// P: creates the column objects of every published segment, entries before
/// the first difference taken from the previous `Listing`.
unsafe fn materialize(shared: &Shared, check: *mut PyObject, previous: Option<&Previous>, columns: &mut Columns)
    -> Result<Materialized> {
    let mut next = 0usize;
    loop {
        let (segments, difference, enumerated) = {
            let _released = Released::new();
            shared.wait(Some(WAKE),
                |state| state.enumerated.is_some() || (state.difference.is_some() && state.segments.len() > next),
                |state| (if state.difference.is_some() { state.segments[next..].to_vec() } else { Vec::new() },
                    state.difference, state.enumerated.as_ref().map(|outcome| outcome.is_ok())))
        };
        let mut started = Instant::now();
        unsafe { call_check(check)? };
        match enumerated {
            Some(false) => {
                let failure = shared.lock().enumerated.take().and_then(|outcome| outcome.err());
                return Err(Error::Failure(failure.unwrap_or(Failure::Canceled)));
            }
            Some(true) if difference.is_none() => return Ok(Materialized::Unchanged),
            _ => {}
        }
        let Some(difference) = difference else { continue };
        for segment in &segments {
            columns.reserve(segment.len())?;
            let start = next << SEG_SHIFT;
            for local in 0..segment.len() {
                if start + local < difference {
                    unsafe { columns.push_previous(previous.unwrap(), start + local) };
                } else {
                    unsafe { columns.push_new(segment, local)? };
                }
            }
            next += 1;
            if started.elapsed() > BUDGET {
                hand_over();
                started = Instant::now();
                unsafe { call_check(check)? };
            }
        }
        if enumerated == Some(true) && next == shared.lock().segments.len() {
            return Ok(Materialized::Complete(started));
        }
    }
}

/// Waits for the order with the GIL released, calling `check_canceled` every
/// WAKE: after a late difference from the previous listing, the keys and the
/// sort of the whole folder are still ahead.
unsafe fn await_order(shared: &Shared, check: *mut PyObject) -> Result<()> {
    loop {
        let ordered = {
            let _released = Released::new();
            shared.wait(Some(WAKE), |state| state.ordered.is_some(), |state| state.ordered.is_some())
        };
        if ordered {
            return Ok(());
        }
        unsafe { call_check(check)? };
    }
}

struct CancelOnDrop<'a>(&'a Shared);

impl Drop for CancelOnDrop<'_> {
    fn drop(&mut self) {
        self.0.cancel();
    }
}

/// scan(path, join_prefix, link_tags, check_canceled, previous)
unsafe extern "C" fn scan(_module: *mut PyObject, args: *const *mut PyObject, count: Py_ssize_t) -> *mut PyObject {
    boundary(|| unsafe { scan_folder(args, count) })
}

unsafe fn scan_folder(args: *const *mut PyObject, count: Py_ssize_t) -> Result<*mut PyObject> {
    let [path, prefix, tags, check, previous_listing] =
        *arguments::<5>(args, count, c"scan() takes 5 arguments")?;
    let request_path = unsafe { wide(path, true)? };
    let join_prefix = unsafe { wide(prefix, false)? };
    let tags = unsafe { sequence(tags)? };
    let mut link_tags = Vec::new();
    for index in 0..unsafe { PyTuple_Size(tags.0) } {
        let value = unsafe { PyLong_AsUnsignedLong(PyTuple_GetItem(tags.0, index)) };
        if value == c_ulong::MAX && unsafe { !PyErr_Occurred().is_null() } {
            return Err(Error::Python);
        }
        link_tags.push(value);
    }
    if unsafe { PyCallable_Check(check) } == 0 {
        return Err(Error::Type(c"check_canceled must be callable"));
    }
    let previous = unsafe { previous_of(previous_listing)? };
    let request = Request { path: request_path, join_prefix, link_tags, previous: previous.as_ref().map(|p| p.table.clone()) };
    let shared = Shared::default();
    let mut columns = Columns::default();
    let opened = {
        let _released = Released::new();
        pipeline::open(&request)
    };
    let built: Result<Option<Owned>> = match opened {
        Err(failure) => Err(Error::Failure(failure)),
        Ok(opened) => std::thread::scope(|scope| {
            // Any exit, unwinding included, tells the threads to stop.
            let _cancel = CancelOnDrop(&shared);
            let (shared, request) = (&shared, &request);
            let mut threads = Vec::new();
            if opened.complete() {
                // The folder ended within the batches `open` read: decoded, keyed and sorted here, without threads.
                let _released = Released::new();
                pipeline::enumerate(shared, request, opened);
                pipeline::order(shared);
            } else {
                threads.push(std::thread::Builder::new().name("fsenum-enumerate".into())
                    .spawn_scoped(scope, move || pipeline::enumerate(shared, request, opened))
                    .map_err(|error| Failure::Thread(error.to_string()))?);
                threads.push(std::thread::Builder::new().name("fsenum-order".into())
                    .spawn_scoped(scope, move || pipeline::order(shared))
                    .map_err(|error| Failure::Thread(error.to_string()))?);
            }
            // Kept here, so tuples left by a failure are released after the threads have stopped.
            let mut tuples = None;
            let outcome = (|| -> Result<Option<Owned>> {
                let materialized = unsafe { materialize(shared, check, previous.as_ref(), &mut columns)? };
                if let Materialized::Complete(mut started) = materialized {
                    tuples = Some(unsafe { columns.into_tuples(&mut started)? });
                }
                unsafe { await_order(shared, check)? };
                // Built before the threads are joined: the key thread frees its keys meanwhile.
                tuples.take().map(|tuples| unsafe { columns_and_table(shared, tuples) }).transpose()
            })();
            if outcome.is_err() {
                shared.cancel();
            }
            // The GIL stays free while the threads finish their current kernel call, sort or free.
            let _released = Released::new();
            for thread in threads {
                let _ = thread.join();
            }
            drop(_released);
            outcome
        }),
    };
    // On a failure, `columns` and the tuples have released their objects in slices.
    match built {
        Err(Error::Failure(Failure::Unsupported)) => Ok(unsafe { new_none() }),
        Err(Error::Failure(Failure::Win32(code))) if UNSUPPORTED.contains(&code) => Ok(unsafe { new_none() }),
        Err(error) => Err(error),
        Ok(None) => {
            unsafe { Py_IncRef(previous_listing) };
            Ok(previous_listing)
        }
        Ok(Some(result)) => Ok(result.into_raw()),
    }
}

/// The result of a complete scan: the six column tuples, the identities, the
/// scope and the table, which takes the segments and the order from `shared`.
unsafe fn columns_and_table(shared: &Shared, tuples: Tuples) -> Result<Owned> {
    let mut state = shared.lock();
    let ordered = match state.ordered.take() {
        Some(Ok(Some(ordered))) => ordered,
        Some(Err(failure)) => return Err(Error::Failure(failure)),
        _ => return Err(Error::Failure(Failure::Panic("the order is missing".into()))),
    };
    let segments = std::mem::take(&mut state.segments);
    let scope_value = state.scope.expect("scope is set before entries");
    drop(state);
    let total = segments.iter().map(|segment| segment.len()).sum();
    let table = Arc::new(Table { segments, count: total, scope: scope_value, ordered });
    unsafe {
        let identities = identities(&table.segments, total)?;
        let scope_tuple = Owned::new(PyTuple_New(2))?;
        PyTuple_SetItem(scope_tuple.0, 0, object(PyLong_FromUnsignedLongLong(scope_value.0))?);
        PyTuple_SetItem(scope_tuple.0, 1, object(PyBytes_FromStringAndSize(scope_value.1.as_ptr().cast(), 16))?);
        let capsule = Owned::new(table_capsule(table)?)?;
        let result = Owned::new(PyTuple_New(9))?;
        for (index, item) in tuples.into_inner().into_iter().chain([identities, scope_tuple, capsule]).enumerate() {
            PyTuple_SetItem(result.0, index as Py_ssize_t, item.into_raw());
        }
        Ok(result)
    }
}

// ---- Table queries ----

/// order(table, ascending) -> bytes of native-endian uint32 entry indices.
unsafe extern "C" fn order(_module: *mut PyObject, args: *const *mut PyObject, count: Py_ssize_t) -> *mut PyObject {
    boundary(|| unsafe {
        let [table, ascending] = *arguments::<2>(args, count, c"order() takes 2 arguments")?;
        let table = table_of(table)?;
        if truth(ascending)? {
            bytes_of_u32(&table.ordered.order)
        } else {
            bytes_of_u32(&table.ordered.descending()?)
        }
    })
}

/// without_attributes(table, order, mask) -> bytes: the entries of `order`
/// (a uint32 buffer) whose own attributes share no bit with `mask`.
unsafe extern "C" fn without_attributes(_module: *mut PyObject, args: *const *mut PyObject, count: Py_ssize_t) -> *mut PyObject {
    boundary(|| unsafe {
        let [table, order, mask] = *arguments::<3>(args, count, c"without_attributes() takes 3 arguments")?;
        let table = table_of(table)?;
        let mask = PyLong_AsUnsignedLong(mask);
        if mask == c_ulong::MAX && !PyErr_Occurred().is_null() {
            return Err(Error::Python);
        }
        let mut view: Py_buffer = std::mem::zeroed();
        if PyObject_GetBuffer(order, &mut view, 0) != 0 {
            return Err(Error::Python);
        }
        let result = (|| {
            if view.len % 4 != 0 {
                return Err(Error::Value(c"order must be a buffer of uint32 values"));
            }
            // An exporter may leave `buf` null for an empty buffer; a slice needs a pointer.
            let entries = if view.len == 0 { &[][..] } else {
                std::slice::from_raw_parts(view.buf.cast::<u8>(), view.len as usize)
            };
            let mut kept = Vec::new();
            kept.try_reserve_exact(entries.len() / 4).map_err(|_| Error::Failure(Failure::Memory))?;
            for chunk in entries.chunks_exact(4) {
                let entry = u32::from_ne_bytes(chunk.try_into().unwrap());
                if entry as usize >= table.count {
                    return Err(Error::Value(c"order entry out of range"));
                }
                if table.attributes(entry as usize) & mask == 0 {
                    kept.push(entry);
                }
            }
            bytes_of_u32(&kept)
        })();
        PyBuffer_Release(&mut view);
        result
    })
}

// ---- Keys for listings without a table ----

/// natural_keys(names, is_dir, ascending) -> tuple[str]: per entry,
/// ('1' if is_dir ^ ascending else '0') + natural_key(name).
unsafe extern "C" fn natural_keys(_module: *mut PyObject, args: *const *mut PyObject, count: Py_ssize_t) -> *mut PyObject {
    boundary(|| unsafe {
        let [names, flags, ascending] = *arguments::<3>(args, count, c"natural_keys() takes 3 arguments")?;
        let names = sequence(names)?;
        let flags = sequence(flags)?;
        let ascending = truth(ascending)?;
        let total = PyTuple_Size(names.0);
        if PyTuple_Size(flags.0) != total {
            return Err(Error::Value(c"names and is_dir differ in length"));
        }
        let result = Owned::new(PyTuple_New(total))?;
        let (mut text, mut key, mut latin1) = (Vec::new(), Vec::new(), Vec::new());
        let mut scratch = Scratch::default();
        for index in 0..total {
            code_points(PyTuple_GetItem(names.0, index), &mut text)?;
            let directory = truth(PyTuple_GetItem(flags.0, index))?;
            key.clear();
            key.push(if directory ^ ascending { b'1' as u32 } else { b'0' as u32 });
            keys::code_points(&text, &mut scratch, &mut Points(&mut key));
            let item = if key.iter().all(|&code| code < 256) {
                latin1.clear();
                latin1.extend(key.iter().map(|&code| code as u8));
                PyUnicode_DecodeLatin1(latin1.as_ptr().cast(), latin1.len() as Py_ssize_t, null_mut())
            } else {
                let mut order: c_int = -1;
                PyUnicode_DecodeUTF32(key.as_ptr().cast(), (key.len() * 4) as Py_ssize_t, c"surrogatepass".as_ptr(), &mut order)
            };
            PyTuple_SetItem(result.0, index, object(item)?);
        }
        Ok(result.into_raw())
    })
}

/// name_order(names, is_dir, ascending) -> bytes: the order a native table of
/// these names would have; the sort's reference check against Python.
unsafe extern "C" fn name_order(_module: *mut PyObject, args: *const *mut PyObject, count: Py_ssize_t) -> *mut PyObject {
    boundary(|| unsafe {
        let [names, flags, ascending] = *arguments::<3>(args, count, c"name_order() takes 3 arguments")?;
        let names = sequence(names)?;
        let flags = sequence(flags)?;
        let ascending = truth(ascending)?;
        let total = PyTuple_Size(names.0) as usize;
        if PyTuple_Size(flags.0) as usize != total {
            return Err(Error::Value(c"names and is_dir differ in length"));
        }
        let mut sorter = Sorter::default();
        let (mut scratch, mut text, mut directories) = (Scratch::default(), Vec::new(), Vec::new());
        for start in (0..total).step_by(SEG) {
            directories.clear();
            for index in start..(start + SEG).min(total) {
                directories.push(truth(PyTuple_GetItem(flags.0, index as Py_ssize_t))? as u8);
            }
            sorter.add(start >> SEG_SHIFT, &directories, |local, bytes| {
                code_points(PyTuple_GetItem(names.0, (start + local) as Py_ssize_t), &mut text)?;
                // The sort pads keys with NUL; folder names never hold one.
                if text.contains(&0) {
                    return Err(Error::Value(c"names must not contain NUL"));
                }
                keys::code_points(&text, &mut scratch, &mut Wtf8(bytes));
                Ok(())
            })?;
        }
        let ordered = Sorter::finish(&[sorter], pipeline::threads())?;
        if ascending { bytes_of_u32(&ordered.order) } else { bytes_of_u32(&ordered.descending()?) }
    })
}

/// parse_batches(batches, link_tags) -> (names, is_dir, sizes, mtimes_ns,
/// attributes, created_ns, identities, link_indices): the scan's record
/// decoding and object creation on given buffers, without link follow-up;
/// the parity check against records().
unsafe extern "C" fn parse_batches(_module: *mut PyObject, args: *const *mut PyObject, count: Py_ssize_t) -> *mut PyObject {
    boundary(|| unsafe {
        let [batches, tags] = *arguments::<2>(args, count, c"parse_batches() takes 2 arguments")?;
        let batches = sequence(batches)?;
        let tags = sequence(tags)?;
        let mut link_tags = Vec::new();
        for index in 0..PyTuple_Size(tags.0) {
            let value = PyLong_AsUnsignedLong(PyTuple_GetItem(tags.0, index));
            if value == c_ulong::MAX && !PyErr_Occurred().is_null() {
                return Err(Error::Python);
            }
            link_tags.push(value);
        }
        let mut segments = vec![Segment::new()?];
        let mut links = Vec::new();
        let mut total = 0usize;
        for index in 0..PyTuple_Size(batches.0) {
            let mut data: *mut c_char = null_mut();
            let mut length: Py_ssize_t = 0;
            if PyBytes_AsStringAndSize(PyTuple_GetItem(batches.0, index), &mut data, &mut length) != 0 {
                return Err(Error::Python);
            }
            let data = std::slice::from_raw_parts(data.cast::<u8>(), length as usize);
            record::for_each(data, |record| -> std::result::Result<(), Failure> {
                if record.attributes & FILE_ATTRIBUTE_REPARSE_POINT != 0 && link_tags.contains(&record.tag) {
                    links.push(total);
                }
                let values = Values {
                    is_dir: record.attributes & FILE_ATTRIBUTE_DIRECTORY != 0,
                    size: record.size as u64,
                    modified: record.modified,
                    created: record.created,
                    attributes: record.attributes,
                    identity: *record.identity,
                };
                if segments.last().unwrap().is_full() {
                    segments.push(Segment::new()?);
                }
                segments.last_mut().unwrap().push(&record, &values)?;
                total += 1;
                Ok(())
            })?;
        }
        let segments: Vec<Arc<Segment>> = segments.into_iter().map(Arc::new).collect();
        let mut columns = Columns::default();
        columns.reserve(total)?;
        for segment in &segments {
            for local in 0..segment.len() {
                columns.push_new(segment, local)?;
            }
        }
        let mut started = Instant::now();
        let tuples = columns.into_tuples(&mut started)?;
        let identities = identities(&segments, total)?;
        let indices = Owned::new(PyTuple_New(links.len() as Py_ssize_t))?;
        for (position, &link) in links.iter().enumerate() {
            PyTuple_SetItem(indices.0, position as Py_ssize_t, object(PyLong_FromUnsignedLongLong(link as u64))?);
        }
        let result = Owned::new(PyTuple_New(8))?;
        for (index, item) in tuples.into_inner().into_iter().chain([identities, indices]).enumerate() {
            PyTuple_SetItem(result.0, index as Py_ssize_t, item.into_raw());
        }
        Ok(result.into_raw())
    })
}

// ---- Module ----

const FASTCALL: c_int = 0x80;

static METHODS: [PyMethodDef; 7] = [
    PyMethodDef { name: c"scan".as_ptr(), method: scan as *const c_void, flags: FASTCALL,
        doc: c"scan(path, join_prefix, link_tags, check_canceled, previous) -> None | previous | columns".as_ptr() },
    PyMethodDef { name: c"order".as_ptr(), method: order as *const c_void, flags: FASTCALL,
        doc: c"order(table, ascending) -> bytes of uint32 entry indices".as_ptr() },
    PyMethodDef { name: c"without_attributes".as_ptr(), method: without_attributes as *const c_void, flags: FASTCALL,
        doc: c"without_attributes(table, order, mask) -> bytes of uint32 entry indices".as_ptr() },
    PyMethodDef { name: c"natural_keys".as_ptr(), method: natural_keys as *const c_void, flags: FASTCALL,
        doc: c"natural_keys(names, is_dir, ascending) -> tuple[str]".as_ptr() },
    PyMethodDef { name: c"name_order".as_ptr(), method: name_order as *const c_void, flags: FASTCALL,
        doc: c"name_order(names, is_dir, ascending) -> bytes of uint32 entry indices".as_ptr() },
    PyMethodDef { name: c"parse_batches".as_ptr(), method: parse_batches as *const c_void, flags: FASTCALL,
        doc: c"parse_batches(batches, link_tags) -> 8 columns".as_ptr() },
    PyMethodDef { name: std::ptr::null(), method: std::ptr::null(), flags: 0, doc: std::ptr::null() },
];

static mut DEFINITION: PyModuleDef = PyModuleDef {
    base: PyModuleDefBase { refcount: 1, kind: null_mut(), init: std::ptr::null(), index: 0, copy: null_mut() },
    name: c"_fsenum".as_ptr(),
    doc: c"Native NTFS/ReFS folder tables (Done/DirectoryEnumerator001.md).".as_ptr(),
    size: -1,
    methods: &METHODS as *const PyMethodDef,
    slots: null_mut(),
    traverse: null_mut(),
    clear: null_mut(),
    free: null_mut(),
};

unsafe fn initialize() -> Result<*mut PyObject> {
    unsafe {
        if GLOBALS.get().is_none() {
            let builtins = Owned::new(PyImport_ImportModule(c"builtins".as_ptr()))?;
            let get = |name: &CStr| object(PyObject_GetAttrString(builtins.0, name.as_ptr()));
            let _ = GLOBALS.set(Globals {
                none: object(Py_BuildValue(c"".as_ptr()))?,
                value_error: get(c"ValueError")?,
                type_error: get(c"TypeError")?,
                runtime_error: get(c"RuntimeError")?,
                os_error: get(c"OSError")?,
            });
        }
        let module = Owned::new(PyModule_Create2(&raw mut DEFINITION, 3))?;
        let version = std::ffi::CString::new(crate::unicode::UNICODE_VERSION).unwrap();
        let text = Owned::new(PyUnicode_FromString(version.as_ptr()))?;
        if PyModule_AddObjectRef(module.0, c"UNICODE_VERSION".as_ptr(), text.0) != 0
            || PyModule_AddIntConstant(module.0, c"HEADER_SIZE".as_ptr(), HEADER as c_long) != 0
            || PyModule_AddIntConstant(module.0, c"SEGMENT_SIZE".as_ptr(), SEG as c_long) != 0 {
            return Err(Error::Python);
        }
        Ok(module.into_raw())
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn PyInit__fsenum() -> *mut PyObject {
    match catch_unwind(|| unsafe { initialize() }) {
        Ok(Ok(module)) => module,
        Ok(Err(error)) => {
            if GLOBALS.get().is_some() {
                unsafe { raise(error) };
            }
            null_mut()
        }
        Err(_) => null_mut(),
    }
}
