//! `_fsenum`: native NTFS/ReFS folder tables (Plan/DirectoryEnumerator001.md).
//!
//! A scan runs as a pipeline: the enumerator thread reads and validates the
//! folder's records (pipeline.rs), the key thread builds natural keys and the
//! Name order while later records are still being read (keys.rs, sort.rs),
//! and the calling thread creates the `Listing` objects from finished
//! segments (python.rs). The result is a `Listing` plus a native table that
//! keeps the order, so the pane does not sort 200,000 names in Python.
//!
//! Read-only: the module opens folders and links for attribute reads only.

pub mod keys;
pub mod pipeline;
pub mod record;
pub mod segment;
pub mod sort;
pub mod unicode;
pub mod win;

#[cfg(not(test))]
mod python;

/// Why native work stopped. The Python boundary turns each into its exception.
#[derive(Debug)]
pub enum Failure {
    /// Not a native NTFS/ReFS folder: the caller uses its fallback scanner.
    Unsupported,
    /// A Win32 error code; the codes the fallback handles also mean Unsupported.
    Win32(u32),
    Record(record::RecordError),
    Memory,
    Canceled,
    Thread(String),
    Panic(String),
}

impl From<record::RecordError> for Failure {
    fn from(error: record::RecordError) -> Failure {
        Failure::Record(error)
    }
}
