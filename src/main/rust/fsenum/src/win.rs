//! Win32 declarations, owned handles and error text. Only kernel32.dll is used.

use std::ffi::c_void;

pub type Handle = *mut c_void;
pub const INVALID_HANDLE: Handle = -1isize as Handle;
pub const ERROR_INVALID_FUNCTION: u32 = 1;
pub const ERROR_FILE_NOT_FOUND: u32 = 2;
pub const ERROR_NO_MORE_FILES: u32 = 18;
pub const ERROR_NOT_SUPPORTED: u32 = 50;
pub const ERROR_INVALID_PARAMETER: u32 = 87;
pub const FILE_LIST_DIRECTORY_READ_ATTRIBUTES: u32 = 0x81;
pub const FILE_READ_ATTRIBUTES: u32 = 0x80;
pub const GENERIC_READ: u32 = 0x8000_0000;
pub const SHARE_READ_WRITE: u32 = 3;
pub const SHARE_ALL: u32 = 7;
pub const OPEN_EXISTING: u32 = 3;
pub const BACKUP_SEMANTICS: u32 = 0x0200_0000;
pub const FILE_ID_INFO: i32 = 18;
pub const FILE_ID_EXTD_DIRECTORY_INFO: i32 = 19;
pub const FILE_ID_EXTD_DIRECTORY_RESTART_INFO: i32 = 20;
pub const FILE_BASIC_INFO: i32 = 0;
pub const FILE_TYPE_DISK: u32 = 1;
pub const FILE_TYPE_UNKNOWN: u32 = 0;
pub const INVALID_FILE_ATTRIBUTES: u32 = u32::MAX;
pub const FILE_SUPPORTS_OPEN_BY_FILE_ID: u32 = 0x0100_0000;
pub const FILE_ATTRIBUTE_DIRECTORY: u32 = 0x10;
pub const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;

#[repr(C)]
#[derive(Default)]
pub struct FileTime {
    pub low: u32,
    pub high: u32,
}

#[repr(C)]
#[derive(Default)]
pub struct ByHandleFileInformation {
    pub attributes: u32,
    pub creation: FileTime,
    pub access: FileTime,
    pub write: FileTime,
    pub volume_serial: u32,
    pub size_high: u32,
    pub size_low: u32,
    pub links: u32,
    pub index_high: u32,
    pub index_low: u32,
}

#[repr(C)]
#[derive(Default)]
pub struct FileBasicInfo {
    pub creation: i64,
    pub access: i64,
    pub write: i64,
    pub change: i64,
    pub attributes: u32,
}

#[link(name = "kernel32", kind = "raw-dylib")]
unsafe extern "system" {
    pub fn CreateFileW(name: *const u16, access: u32, share: u32, security: *mut c_void,
        disposition: u32, flags: u32, template: Handle) -> Handle;
    pub fn CloseHandle(handle: Handle) -> i32;
    pub fn GetFileInformationByHandleEx(handle: Handle, class: i32, buffer: *mut c_void, size: u32) -> i32;
    pub fn GetFinalPathNameByHandleW(handle: Handle, path: *mut u16, length: u32, flags: u32) -> u32;
    pub fn GetVolumeInformationByHandleW(handle: Handle, volume_name: *mut u16, volume_name_size: u32,
        serial: *mut u32, max_component: *mut u32, flags: *mut u32, file_system: *mut u16,
        file_system_size: u32) -> i32;
    pub fn GetFileInformationByHandle(handle: Handle, information: *mut ByHandleFileInformation) -> i32;
    pub fn GetFileType(handle: Handle) -> u32;
    pub fn GetFileAttributesW(name: *const u16) -> u32;
    pub fn GetLastError() -> u32;
    pub fn FormatMessageW(flags: u32, source: *const c_void, message: u32, language: u32,
        buffer: *mut u16, size: u32, arguments: *mut c_void) -> u32;
    pub fn LocalFree(memory: *mut c_void) -> *mut c_void;
}

pub fn last_error() -> u32 {
    unsafe { GetLastError() }
}

/// A handle closed on every exit path, including unwinding.
pub struct OwnedHandle(pub Handle);

// SAFETY: Windows handles may be used from any thread; Drop closes it once.
unsafe impl Send for OwnedHandle {}
unsafe impl Sync for OwnedHandle {}

impl OwnedHandle {
    /// CreateFileW with `path` NUL-terminated; Err(last error) on failure.
    pub fn open(path: &[u16], access: u32, share: u32, flags: u32) -> Result<OwnedHandle, u32> {
        debug_assert_eq!(path.last(), Some(&0));
        let handle = unsafe {
            CreateFileW(path.as_ptr(), access, share, std::ptr::null_mut(), OPEN_EXISTING, flags, std::ptr::null_mut())
        };
        if handle == INVALID_HANDLE { Err(last_error()) } else { Ok(OwnedHandle(handle)) }
    }
}

impl Drop for OwnedHandle {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0);
        }
    }
}

/// The text ctypes.FormatError(code).strip() gives, as UTF-16.
pub fn format_message(code: u32) -> Vec<u16> {
    const ALLOCATE: u32 = 0x100;
    const FROM_SYSTEM: u32 = 0x1000;
    const IGNORE_INSERTS: u32 = 0x200;
    let mut buffer: *mut u16 = std::ptr::null_mut();
    let length = unsafe {
        FormatMessageW(ALLOCATE | FROM_SYSTEM | IGNORE_INSERTS, std::ptr::null(), code, 0x400,
            (&mut buffer as *mut *mut u16).cast(), 0, std::ptr::null_mut())
    };
    if length == 0 || buffer.is_null() {
        return "<no description>".encode_utf16().collect();
    }
    let text = unsafe { std::slice::from_raw_parts(buffer, length as usize) }.to_vec();
    unsafe {
        LocalFree(buffer.cast());
    }
    let is_space = |unit: &u16| matches!(*unit, 0x09..=0x0D | 0x20 | 0x85 | 0xA0 | 0x3000 | 0x2000..=0x200A | 0x2028 | 0x2029);
    let start = text.iter().position(|unit| !is_space(unit)).unwrap_or(text.len());
    let end = text.iter().rposition(|unit| !is_space(unit)).map_or(start, |index| index + 1);
    text[start..end].to_vec()
}
