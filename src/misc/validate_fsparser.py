"""Edge-case validation of the native directory parser (Done/FSParser.md).

Creates a folder of unusual entries on a real NTFS volume, enumerates it once,
and checks that every native shape of ``_fsparser`` produces exactly what the
Python parser produces, that the planned native ``scan()`` yields the same
``Listing`` as the current one, and that both agree with ``os.lstat``/``os.stat``
for every entry. Correctness only; no timing.

Also checks crafted buffers the file system cannot produce (malformed records,
FILETIME and size extremes), the ``Columns``/``parse_batch`` contracts, error-path
leaks, and read-only system folders with special reparse points.

    python src/misc/validate_fsparser.py [--root FOLDER] [--keep] [--no-external]
                                         [--native path/to/_fsparser.pyd]

Cases that the machine cannot create (privilege, filesystem feature) are
reported as skipped, not as failures. Exit code 0: every created case agrees
on every path. Exit code 1: a mismatch. Exit code 2: setup problem.
"""

import argparse
import ctypes
from ctypes import wintypes
import gc
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import benchmark_fsparser as gauge  # noqa: E402
from core.fs.local.windows import listing as scanner  # noqa: E402

EPOCH_NS = 0
ONE_NS = 1
FILETIME_EPOCH = scanner._EPOCH
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.SetFileTime.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
kernel32.SetFileAttributesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
kernel32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
INVALID_HANDLE = wintypes.HANDLE(-1).value

FILE_ATTRIBUTE_READONLY = 0x1
FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4
FILE_ATTRIBUTE_ARCHIVE = 0x20
FILE_ATTRIBUTE_TEMPORARY = 0x100
FILE_ATTRIBUTE_NOT_CONTENT_INDEXED = 0x2000
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FSCTL_SET_SPARSE = 0x900C4
FSCTL_SET_COMPRESSION = 0x9C040
HARDLINKS = (
    ('hardlink.txt', 'plain.txt'),
    ('hardlink-second.txt', 'plain.txt'),
    ('hardlink-chain.txt', 'hardlink.txt'),
)
INT64_MIN, INT64_MAX = -2**63, 2**63 - 1
FAST_MIN = FILETIME_EPOCH - (2**63 // 100)
FAST_MAX = FILETIME_EPOCH + INT64_MAX // 100
APP_EXEC_LINK = 0x8000001B
CLOUD_TAG = 0x9000601A


def extended(path):
    """Win32 path with the \\\\?\\ prefix: allows trailing dots/spaces, reserved names, long paths.

    No normalisation: os.path.abspath would strip the very characters under test.
    """
    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)
    return path if path.startswith('\\\\?\\') else '\\\\?\\' + path


class Cases:
    """Creates entries and records what was created or skipped."""

    def __init__(self, root):
        self.root = root
        self.created = {}   # case label -> description
        self.skipped = {}   # case label -> reason
        self.entries = set()  # names expected in the listing
        self.folders = []   # (label, path) validated as separate listings

    def attempt(self, label, description, action, entry=None):
        try:
            action()
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            self.skipped[label] = '%s: %s' % (description, error)
        else:
            self.created[label] = description
            if entry is not None:
                self.entries.add(entry)

    def file(self, name, size=0, description=None, attributes=None):
        path = extended(os.path.join(self.root, name))

        def action():
            with open(path, 'wb') as handle:
                if size:
                    handle.seek(size - 1)
                    handle.write(b'\0')
            if attributes is not None and not kernel32.SetFileAttributesW(path, attributes):
                raise ctypes.WinError(ctypes.get_last_error())
        self.attempt(name, description or 'file of %d bytes' % size, action, entry=name)

    def folder(self, name, description='folder'):
        self.attempt(name, description, lambda: os.mkdir(extended(os.path.join(self.root, name))), entry=name)

    def attributes(self, name, attributes):
        path = extended(os.path.join(self.root, name))

        def action():
            if not kernel32.SetFileAttributesW(path, attributes):
                raise ctypes.WinError(ctypes.get_last_error())
        self.attempt(name + ' (attributes)', 'attributes %#x' % attributes, action)

    def times(self, name, mtime_ns=None, raw_filetimes=None):
        """Set times through os.utime (ns) or SetFileTime (raw FILETIME ints: created, written)."""
        path = extended(os.path.join(self.root, name))

        def action():
            if mtime_ns is not None:
                os.utime(path, ns=(mtime_ns, mtime_ns))
            if raw_filetimes is not None:
                created, written = raw_filetimes
                handle = kernel32.CreateFileW(path, 0x100, 7, None, 3, 0x02000000, None)
                if handle == INVALID_HANDLE:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    created_ft = wintypes.FILETIME(created & 0xFFFFFFFF, created >> 32)
                    written_ft = wintypes.FILETIME(written & 0xFFFFFFFF, written >> 32)
                    if not kernel32.SetFileTime(handle, ctypes.byref(created_ft), None, ctypes.byref(written_ft)):
                        raise ctypes.WinError(ctypes.get_last_error())
                finally:
                    kernel32.CloseHandle(handle)
        self.attempt(name + ' (times)', 'timestamps', action)

    def ioctl(self, name, code, payload=None, description='ioctl'):
        path = extended(os.path.join(self.root, name))

        def action():
            handle = kernel32.CreateFileW(path, 0xC0000000, 7, None, 3, 0x02000000, None)
            if handle == INVALID_HANDLE:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                returned = wintypes.DWORD()
                buffer = ctypes.byref(payload) if payload is not None else None
                size = ctypes.sizeof(payload) if payload is not None else 0
                if not kernel32.DeviceIoControl(handle, code, buffer, size, None, 0, ctypes.byref(returned), None):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                kernel32.CloseHandle(handle)
        self.attempt(name + ' (%s)' % description, description, action)

    def junction(self, name, target):
        def action():
            subprocess.run(['cmd', '/c', 'mklink', '/J', os.path.join(self.root, name), target],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.attempt(name, 'junction -> %s' % target, action, entry=name)

    def symlink(self, name, target, directory):
        self.attempt(name, '%s symlink -> %s' % ('directory' if directory else 'file', target),
            lambda: os.symlink(target, os.path.join(self.root, name), target_is_directory=directory), entry=name)

    def hardlink(self, name, source):
        self.attempt(name, 'hard link of %s' % source,
            lambda: os.link(os.path.join(self.root, source), os.path.join(self.root, name)), entry=name)

    def stream(self, name, stream, size):
        def action():
            with open(extended(os.path.join(self.root, name)) + ':' + stream, 'wb') as handle:
                handle.write(b's' * size)
        self.attempt('%s:%s' % (name, stream), 'alternate data stream of %d bytes' % size, action)


def populate_folders(cases):
    """Subfolders validated as their own listings: shapes the main folder cannot have."""
    root = cases.root
    cases.folders.append(('empty folder (only . and ..)', os.path.join(root, 'empty-folder')))

    single = os.path.join(root, 'single')
    cases.attempt('single', 'folder with one entry', lambda: (os.mkdir(single),
        open(os.path.join(single, 'only.txt'), 'wb').close()))
    cases.folders.append(('single entry', single))

    # Names 1-255 characters long move record boundaries across many 64 KiB batches.
    many = os.path.join(root, 'many-batches')

    def fill_many():
        os.mkdir(many)
        for index in range(2500):
            length = 1 + index % 255
            name = ('%05d' % index + 'm' * length)[:max(length, 5)]
            open(extended(os.path.join(many, name)), 'wb').close()
    cases.attempt('many-batches', '2,500 entries with 5-255 character names', fill_many)
    cases.folders.append(('many batches', many))

    # Names differing only in case need a case-sensitive directory.
    sensitive = os.path.join(root, 'case-sensitive')

    def fill_sensitive():
        os.mkdir(sensitive)
        subprocess.run(['fsutil', 'file', 'setCaseSensitiveInfo', sensitive, 'enable'],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for name in ('Name.txt', 'name.txt', 'NAME.txt'):
            open(os.path.join(sensitive, name), 'wb').close()
        if len(os.listdir(sensitive)) != 3:
            raise OSError('directory is not case sensitive')
    cases.attempt('case-sensitive', 'names differing only in case', fill_sensitive)
    if 'case-sensitive' in cases.created:
        cases.folders.append(('case-sensitive', sensitive))

    # A folder whose own path exceeds MAX_PATH; the scanner opens it through \\?\.
    deep = extended(root)

    def fill_deep():
        nonlocal deep
        while len(deep) < 320:
            deep = os.path.join(deep, 'd' * 60)
            os.mkdir(deep)
        for name in ('deep-file.txt', 'deep-other.bin'):
            with open(os.path.join(deep, name), 'wb') as handle:
                handle.write(b'x' * len(name))
    cases.attempt('deep', 'folder path above 260 characters', fill_deep)
    if 'deep' in cases.created:
        # scan() receives plain paths, as from LocalFileSystem; NativeDirectory adds \\?\ itself.
        cases.folders.append(('path above MAX_PATH', deep.removeprefix('\\\\?\\')))


def populate(cases):
    root = cases.root
    # Names: Unicode planes, normalisation forms, directionality, punctuation, length.
    cases.file('plain.txt', 10)
    cases.file('\U0001F600 emoji \U0001F30D.txt', 1)
    cases.file('e\u0301 decomposed.txt', 1)
    cases.file('\u00e9 composed.txt', 1)
    cases.file('caf\u00e9.txt', 1, 'NFC name paired with its NFD equivalent')
    cases.file('cafe\u0301.txt', 2, 'NFD name paired with its NFC equivalent')
    cases.file('\ufeffbom.txt', 1, 'leading BOM is part of the name')
    cases.file('zero\u200bwidth.txt', 1, 'zero-width space in name')
    cases.file('literal%2F%5C%00.txt', 1, 'percent escapes are literal filename characters')
    cases.file('\u05e9\u05dc\u05d5\u05dd \u0639\u0631\u0628\u064a.txt', 1)
    cases.file('\u4e2d\u6587 \u65e5\u672c\u8a9e \ud55c\uae00.txt', 1)
    cases.file('.hidden-dot-name', 1)
    cases.file('..two-dots-prefix', 1)
    cases.file('...', 1, 'three-dot name')
    cases.file('trailing.', 1, 'trailing dot')
    cases.file('trailing ', 1, 'trailing space')
    cases.file(' leading space', 1)
    cases.file('CON', 1, 'reserved device name')
    cases.file('NUL.txt', 1, 'reserved device name with extension')
    cases.file("quote's `tick` %percent% #hash [bracket] (paren) {brace} !bang ~tilde", 1)
    cases.file('a', 1, 'single-character name')
    cases.file('x' * 255, 1, '255-character name')
    cases.file('a' + '\U0001F600' * 125 + '.txt', 1, '255 UTF-16 code units with surrogate pairs')
    cases.file('lone\udc80surrogate.txt', 1, 'lone surrogate in name')
    cases.file('lone\ud800high-surrogate.txt', 1, 'lone high surrogate in name')
    cases.file('dup', 1, 'name that differs from the next only by a trailing dot')
    cases.file('dup.', 2, 'trailing-dot twin of dup')
    cases.file('wsl\uf02a\uf03a\uf05c.txt', 1, 'private-use characters WSL uses for * : \\')
    cases.file('nonchar\ufffe\uffff.txt', 1, 'Unicode noncharacters')
    cases.file('line\u2028para\u2029.txt', 1, 'line and paragraph separators')
    cases.file('del\x7f.txt', 1, 'DEL character')
    cases.file('control\x01.txt', 1, 'C0 control character')
    cases.file('ads.txt', 3, 'file with an alternate data stream')
    cases.stream('ads.txt', 'extra', 1000)
    cases.folder('ads-folder', 'folder with an alternate data stream')
    cases.stream('ads-folder', 'extra', 10)
    cases.folder('folder.txt', 'folder with a file extension')
    cases.folder('readonly-folder')
    cases.attributes('readonly-folder', 0x11)
    for length in range(1, 17):
        cases.file('pad-' + 'n' * length, 1, 'name length %d (record padding)' % (4 + length))
    # Sizes: boundaries and above 4 GiB (sparse).
    for size in (0, 1, 4095, 4096, 4097, 65535, 65536, 2**20):
        cases.file('size-%d.bin' % size, size)
    cases.file('sparse-5GiB.bin', 0, 'sparse file, 5 GiB logical size')
    cases.ioctl('sparse-5GiB.bin', FSCTL_SET_SPARSE, description='sparse flag')
    cases.attempt('sparse-5GiB.bin (extend)', 'extend to 5 GiB',
        lambda: os.truncate(extended(os.path.join(root, 'sparse-5GiB.bin')), 5 * 2**30 + 7))
    # Attributes.
    cases.file('readonly.txt', 1, 'read-only', FILE_ATTRIBUTE_READONLY)
    cases.file('hidden.txt', 1, 'hidden', FILE_ATTRIBUTE_HIDDEN)
    cases.file('system-hidden.txt', 1, 'system + hidden', FILE_ATTRIBUTE_SYSTEM | FILE_ATTRIBUTE_HIDDEN)
    cases.file('temporary.txt', 1, 'temporary', FILE_ATTRIBUTE_TEMPORARY)
    cases.file('not-indexed.txt', 1, 'not content indexed', FILE_ATTRIBUTE_NOT_CONTENT_INDEXED)
    cases.file('no-archive.txt', 1, 'archive bit cleared', 0x80)
    cases.file('compressed.txt', 4096 * 4, 'compressed')
    cases.ioctl('compressed.txt', FSCTL_SET_COMPRESSION, ctypes.c_ushort(1), 'compression')
    cases.folder('empty-folder')
    cases.folder('hidden-folder')
    cases.attributes('hidden-folder', 0x12)
    cases.folder('nested')
    cases.attempt('nested/deep', 'nested folders', lambda: os.makedirs(os.path.join(root, 'nested', 'a', 'b', 'c')))
    # Timestamps: epoch, pre-1970, far future, raw FILETIME extremes.
    cases.file('time-epoch.txt', 1)
    cases.times('time-epoch.txt', mtime_ns=EPOCH_NS)
    cases.file('time-1960.txt', 1)
    cases.times('time-1960.txt', mtime_ns=-315619200 * 10**9)
    cases.file('time-2038.txt', 1)
    cases.times('time-2038.txt', mtime_ns=2**31 * 10**9)
    cases.file('time-9999.txt', 1)
    cases.times('time-9999.txt', mtime_ns=253402300799 * 10**9)
    cases.file('time-odd-ns.txt', 1)
    cases.times('time-odd-ns.txt', mtime_ns=1_700_000_000_123_456_789)
    cases.file('time-filetime-1.txt', 1)
    cases.times('time-filetime-1.txt', raw_filetimes=(1, 1))
    cases.file('time-filetime-max.txt', 1)
    cases.times('time-filetime-max.txt', raw_filetimes=(2**63 - 1, 2**63 - 1))
    cases.file('time-filetime-year30000.txt', 1)
    cases.times('time-filetime-year30000.txt', raw_filetimes=(0x7FFF35F4F06C58F0 // 2, 0x7FFF35F4F06C58F0 // 2))
    for label, boundary in (
            ('fast-min', FILETIME_EPOCH - (2**63 // 100)),
            ('fast-max', FILETIME_EPOCH + (2**63 - 1) // 100)):
        for delta in (-1, 0, 1):
            name = 'time-%s-%+d.txt' % (label, delta)
            cases.file(name, 1)
            cases.times(name, raw_filetimes=(boundary + delta, boundary + delta))
    # Different created and written values catch swapped header offsets.
    cases.file('time-created-old-written-max.txt', 1)
    cases.times('time-created-old-written-max.txt', raw_filetimes=(1, FAST_MAX + 1))
    cases.file('time-created-max-written-old.txt', 1)
    cases.times('time-created-max-written-old.txt', raw_filetimes=(FAST_MAX + 1, FAST_MIN - 1))
    # Links and identities.
    cases.folder('link-target')
    cases.file('link-target-file.txt', 3)
    cases.junction('junction', os.path.join(root, 'link-target'))
    cases.junction('junction-dangling', os.path.join(root, 'does-not-exist'))
    cases.junction('junction-self', os.path.join(root, 'junction-self'))
    cases.junction('junction-parent', root)
    cases.symlink('symlink-dir', os.path.join(root, 'link-target'), True)
    cases.symlink('symlink-file', os.path.join(root, 'link-target-file.txt'), False)
    cases.symlink('symlink-dangling', os.path.join(root, 'missing.txt'), False)
    cases.symlink('symlink-relative-dir', 'link-target', True)
    cases.symlink('symlink-relative-file', 'link-target-file.txt', False)
    cases.symlink('symlink-dangling-dir', 'missing-directory', True)
    cases.symlink('symlink-chain', 'symlink-relative-file', False)
    cases.symlink('symlink-self', 'symlink-self', False)
    cases.symlink('symlink-cycle-a', 'symlink-cycle-b', False)
    cases.symlink('symlink-cycle-b', 'symlink-cycle-a', False)
    cases.symlink('symlink-dir-to-file', 'link-target-file.txt', True)
    cases.symlink('symlink-file-to-dir', 'link-target', False)
    cases.junction('junction-chain', os.path.join(root, 'junction'))
    for name, source in HARDLINKS:
        cases.hardlink(name, source)
    # Volume: enough entries for several 64 KiB batches with varied record lengths.
    for index in range(1200):
        cases.file('bulk-%04d-%s.dat' % (index, 'y' * (index % 90)), index % 7)
    populate_folders(cases)


def check_against_os(listing, root, problems):
    """Every entry agrees with os.lstat (own metadata) or os.stat (followed links)."""
    index_of = {name: index for index, name in enumerate(listing.names)}
    for name, index in index_of.items():
        path = extended(os.path.join(root, name))
        try:
            own = os.lstat(path)
        except OSError as error:
            problems.append('%s: lstat failed: %s' % (name, error))
            continue
        identity = int.from_bytes(listing.identity(index)[0], 'little')
        if identity != own.st_ino:
            problems.append('%s: file ID %#x vs lstat %#x' % (name, identity, own.st_ino))
        if listing.attributes[index] != own.st_file_attributes:
            problems.append('%s: attributes %#x vs lstat %#x' % (name, listing.attributes[index], own.st_file_attributes))
        if own.st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT and own.st_reparse_tag in scanner._LINK_TAGS:
            try:
                target = os.stat(path)
            except OSError:
                target = own
        else:
            target = own
        expected = (stat.S_ISDIR(target.st_mode), target.st_size, target.st_mtime_ns)
        actual = (listing.is_dir[index], listing.sizes[index], listing.mtimes_ns[index])
        if target is own and stat.S_ISDIR(own.st_mode):
            # The parent's index reports 0 for a folder; lstat reports its index allocation.
            expected, actual = expected[::2], actual[::2]
        if expected != actual:
            problems.append('%s: (is_dir, size, mtime_ns) %r vs stat %r' % (name, actual, expected))
        if listing.created_ns[index] != own.st_birthtime_ns:
            problems.append('%s: created_ns %d vs lstat %d' % (name, listing.created_ns[index], own.st_birthtime_ns))
    expected_duplicates = 0
    for name, source in HARDLINKS:
        hard = index_of.get(name)
        original = index_of.get(source)
        if hard is not None and original is not None:
            expected_duplicates += 1
            if listing.identity(hard)[0] != listing.identity(original)[0]:
                problems.append('%s and its source %s report different file IDs' % (name, source))
    identities = [listing.identity(index)[0] for index in range(len(listing.names))]
    duplicates = len(identities) - len(set(identities)) - expected_duplicates
    if duplicates:
        problems.append('%d unexpected duplicate file IDs' % duplicates)


def validate_folder(native, folder, label, problems, check_os=True):
    """All native shapes and the native scan against the Python parser for one folder."""
    found = []
    batches, scope, _ = gauge.enumerate_batches(folder)
    location = 'file:///' + folder.replace('\\', '/')
    python_columns = gauge.python_columns(batches)
    for shape, result in (
            ('parse_records', native.parse_records(batches)),
            ('parse_batch', gauge.native_columns(native.parse_batch, batches)),
            ('Columns', gauge.accumulator_columns(native.Columns, batches)),
            ('Columns frozen', gauge.accumulator_columns(native.Columns, batches, frozen=True))):
        mismatch = gauge.compare_columns(python_columns, result)
        if mismatch:
            found.append('%s vs records(): %s' % (shape, mismatch))
    python_listing = gauge.python_scan(location, folder, batches, scope)
    native_listing = gauge.native_scan(native, location, folder, batches, scope)
    mismatch = gauge.compare_listings(python_listing, native_listing)
    if mismatch:
        found.append('native scan vs python scan: %s' % mismatch)
    if check_os:
        check_against_os(python_listing, folder, found)
        check_against_os(native_listing, folder, found)
    problems.extend('[%s] %s' % (label, problem) for problem in found)
    return python_listing, batches


# ---- Crafted buffers: records the file system cannot produce ----

def record(name='entry.txt', created=FILETIME_EPOCH, modified=FILETIME_EPOCH, size=1,
        attributes=FILE_ATTRIBUTE_ARCHIVE, tag=0, identity=bytes(range(16)), name_length=None,
        next_offset=0, raw_name=None):
    raw = name.encode('utf-16-le', 'surrogatepass') if raw_name is None else raw_name
    length = len(raw) if name_length is None else name_length
    return scanner._RECORD.pack(next_offset, 0, created, 0, modified, 0, size, 0, attributes,
        length, 0, tag, identity) + raw


def chain(*records, gap=0, tail=b'\0' * 64):
    """Link records with 8-byte aligned NextEntryOffset plus `gap` bytes; the last one ends the chain."""
    out = bytearray()
    for index, item in enumerate(records):
        if index < len(records) - 1:
            padded = item + bytes(-len(item) % 8 + gap)
            out += len(padded).to_bytes(4, 'little') + padded[4:]
        else:
            out += (0).to_bytes(4, 'little') + item[4:]
    return bytes(out) + tail


def valid_synthetic_batches():
    times = (INT64_MIN, INT64_MIN + 1, -1, 0, 1, FAST_MIN - 1, FAST_MIN, FAST_MAX, FAST_MAX + 1,
        INT64_MAX, FILETIME_EPOCH - 1, FILETIME_EPOCH, FILETIME_EPOCH + 1)
    extremes = [record('t%02d' % index, created=value, modified=times[-1 - index])
        for index, value in enumerate(times)]
    extremes += [
        record('size-max', size=INT64_MAX),
        record('size-zero', size=0),
        record('attributes-all', attributes=0xFFFFFFFF, tag=0xFFFFFFFF),
        record('identity-ff', identity=b'\xff' * 16),
        record('identity-zero', identity=bytes(16)),
        record('directory-with-size', attributes=0x10, size=4096),
    ]
    names = [record(name) for name in (
        '\ufeffbom', '\ufffereversed-bom', 'lone\udc80low', 'lone\ud800high',
        '\U0001F600pair', '...', '.x', 'x.', '. ', 'dot-like\u2024', 'L' * 255)]
    names.insert(3, record('.', attributes=0x10))
    names.insert(7, record('..', attributes=0x10))
    return {
        'FILETIME, size, attribute and identity extremes': [chain(*extremes)],
        'names, with . and .. in the middle': [chain(*names)],
        'only . and ..': [chain(record('.', attributes=0x10), record('..', attributes=0x10))],
        'no batches': [],
        'single record without tail': [record('alone')],
        'records 4 KiB apart, non-zero tail': [chain(record('a'), record('b'), record('c'), gap=4096,
            tail=b'\xa5' * 300)],
        'name of 32,000 UTF-16 units': [chain(record('n' * 32000))],
        'many small batches': [chain(record('b%04d' % index)) for index in range(2000)],
    }


def malformed_batches():
    valid = record('valid.txt')
    padded = valid + bytes(-len(valid) % 8)
    return {
        'empty buffer': b'',
        'truncated header': record('x')[:87],
        'zero name length': record(raw_name=b'', name_length=0) + bytes(16),
        'odd name length': record(raw_name=b'abc', name_length=3) + bytes(16),
        'name past buffer end': record(raw_name=b'a\0', name_length=200),
        'huge even name length': record(raw_name=b'a\0', name_length=0xFFFFFFFE),
        'negative size': record(size=-1) + bytes(16),
        'size INT64_MIN': record(size=INT64_MIN) + bytes(16),
        'next offset unaligned': record(next_offset=len(padded) + 4) + bytes(200),
        'next offset below record length': record(next_offset=8) + bytes(200),
        'next offset past end': record(next_offset=len(padded)) + bytes(8),
        'next offset 0xFFFFFFF8': record(next_offset=0xFFFFFFF8) + bytes(200),
        'second record invalid': chain(valid, record(raw_name=b'', name_length=0)),
        'third record truncated': chain(valid, valid, tail=b'')[:-10],
        # Names other NTFS drivers can write; Listing rejects them, so both parsers must.
        'NUL in name': chain(valid, record('nul\x00inside')),
        'slash in name': chain(valid, record('a/b')),
        'backslash in name': chain(valid, record('a\\b')),
    }


def outcome(function):
    try:
        return 'ok', function()
    except Exception as error:  # noqa: BLE001 - the exception itself is the result under test
        return type(error).__name__, str(error)


def new_columns():
    return [], [], [], [], [], [], bytearray(), []


def check_synthetic(native, problems):
    for label, batches in valid_synthetic_batches().items():
        expected = gauge.python_columns(batches)
        for shape, function in (
                ('parse_records', lambda: native.parse_records(batches)),
                ('parse_batch', lambda: gauge.native_columns(native.parse_batch, batches)),
                ('Columns', lambda: gauge.accumulator_columns(native.Columns, batches)),
                ('Columns frozen', lambda: gauge.accumulator_columns(native.Columns, batches, frozen=True))):
            status, result = outcome(function)
            mismatch = result if status != 'ok' else gauge.compare_columns(expected, result)
            if mismatch:
                problems.append('[synthetic] %s, %s: %s' % (label, shape, mismatch))

    prefix = chain(record('kept-1'), record('kept-2'))
    kept = gauge.python_columns([prefix])
    for label, batch in malformed_batches().items():
        expected = outcome(lambda: list(scanner.records(batch)))
        if expected[0] != 'ValueError':
            problems.append('[malformed] %s: records() gave %r, expected ValueError' % (label, expected))
            continue
        results = {'parse_records': outcome(lambda: native.parse_records([prefix, batch]))}
        columns = new_columns()
        native.parse_batch(prefix, *columns)
        results['parse_batch'] = outcome(lambda: native.parse_batch(batch, *columns))
        after_batch = tuple(columns[:6]) + (bytes(columns[6]), columns[7])
        accumulator = native.Columns(scanner._LINK_TAGS)
        accumulator.add(prefix)
        results['Columns.add'] = outcome(lambda: accumulator.add(batch))
        after_add = (len(accumulator), accumulator.finish())
        for shape, result in results.items():
            if result != expected:
                problems.append('[malformed] %s, %s: %r, records() %r' % (label, shape, result, expected))
        if gauge.compare_columns(kept, after_batch):
            problems.append('[malformed] %s: parse_batch changed the columns on error' % label)
        if after_add[0] != 2 or gauge.compare_columns(kept, after_add[1]):
            problems.append('[malformed] %s: Columns.add kept entries on error' % label)


def check_contracts(native, problems):
    """Argument types, link reporting, patch rules and the finished state."""
    link, junction = 0xA000000C, 0xA0000003
    batch = chain(
        record('symlink', attributes=0x420, tag=link),
        record('junction', attributes=0x410, tag=junction),
        record('app-exec-link', attributes=0x420, tag=APP_EXEC_LINK),
        record('cloud', attributes=0x420, tag=CLOUD_TAG),
        record('tag-without-attribute', attributes=0x20, tag=link),
        record('plain'))
    expectations = []

    def expect(label, function, error=None, value=None):
        status, result = outcome(function)
        if error is not None and status != error:
            expectations.append('%s: %s %r, expected %s' % (label, status, result, error))
        elif error is None and (status != 'ok' or (value is not None and result != value)):
            expectations.append('%s: %s %r, expected %r' % (label, status, result, value))

    for kind in (bytearray, memoryview):
        expect('parse_records(%s)' % kind.__name__, lambda: native.parse_records([kind(batch)]), 'TypeError')
        expect('parse_batch(%s)' % kind.__name__, lambda: native.parse_batch(kind(batch), *new_columns()), 'TypeError')
        expect('Columns.add(%s)' % kind.__name__, lambda: native.Columns(()).add(kind(batch)), 'TypeError')
    expect('parse_records(None)', lambda: native.parse_records(None), 'TypeError')
    expect('parse_batch(tuple column)', lambda: native.parse_batch(batch, (), *new_columns()[1:]), 'TypeError')
    expect('Columns()', lambda: native.Columns(), 'TypeError')
    expect('Columns([-1])', lambda: native.Columns([-1]), 'OverflowError')
    expect('Columns([2**32])', lambda: native.Columns([2**32]), 'OverflowError')

    columns = native.Columns(scanner._LINK_TAGS)
    expect('add() reports link-tagged reparse points only', lambda: columns.add(batch), value=[0, 1])
    expect('add() reports absolute indices', lambda: columns.add(batch), value=[6, 7])
    expect('len(Columns)', lambda: len(columns), value=12)
    expect('entry()', lambda: columns.entry(6), value=('symlink', 0x420, link))
    expect('entry(-1)', lambda: columns.entry(-1), 'IndexError')
    expect('entry(len)', lambda: columns.entry(12), 'IndexError')
    expect('patch(bool size)', lambda: columns.patch(0, True, True, 0), 'TypeError')
    expect('patch(bool mtime)', lambda: columns.patch(0, True, 0, False), 'TypeError')
    expect('patch(int is_dir)', lambda: columns.patch(0, 1, 0, 0), 'TypeError')
    expect('patch(negative size)', lambda: columns.patch(0, True, -1, 0), 'ValueError')
    expect('patch(index out of range)', lambda: columns.patch(12, True, 0, 0), 'IndexError')
    expect('patch(size above int64)', lambda: columns.patch(0, False, 2**70, INT64_MIN * 100))
    expect('patch()', lambda: columns.patch(1, True, 5, 7))
    status, result = outcome(lambda: columns.finish(frozen=True))
    if status != 'ok':
        expectations.append('finish(frozen=True): %s %r' % (status, result))
    else:
        names, is_dir, sizes, mtimes = result[:4]
        if (is_dir[0], sizes[0], mtimes[0]) != (False, 2**70, INT64_MIN * 100) or \
                (is_dir[1], sizes[1], mtimes[1]) != (True, 5, 7):
            expectations.append('patched values not returned by finish()')
        if any(type(column) is not tuple for column in result[:6] + result[7:]):
            expectations.append('finish(frozen=True) returned a non-tuple column')
    expect('finish() twice', lambda: columns.finish(), 'ValueError')
    expect('add() after finish', lambda: columns.add(batch), 'ValueError')
    expect('patch() after finish', lambda: columns.patch(0, True, 0, 0), 'ValueError')
    expect('len() after finish', lambda: len(columns), value=0)
    expect('empty finish()', lambda: native.Columns(()).finish(),
        value=([], [], [], [], [], [], b'', []))
    problems.extend('[contract] ' + problem for problem in expectations)


def check_leaks(native, problems, rounds=300):
    """Error paths and full Columns lifecycles must not grow traced memory."""
    good = chain(*(record('leak-%03d' % index, attributes=0x420 if index % 5 else 0x20,
        tag=0xA000000C) for index in range(200)))
    bad = list(malformed_batches().values())

    def cycle():
        native.parse_records([good])
        for number, batch in enumerate(bad):
            outcome(lambda: native.parse_records([good, batch]))
            outcome(lambda: native.parse_batch(batch, *new_columns()))
            columns = native.Columns(scanner._LINK_TAGS)
            columns.add(good)
            outcome(lambda: columns.add(batch))
            for index in columns.add(good):
                columns.patch(index, True, 1, 1)
            columns.finish(frozen=bool(number % 2))
        native.Columns(()).add(good)  # dropped without finish()

    for _ in range(20):
        cycle()
    gc.collect()
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        for _ in range(rounds):
            cycle()
        gc.collect()
        growth = tracemalloc.get_traced_memory()[0] - before
    finally:
        tracemalloc.stop()
    if growth > 256 * 1024:
        problems.append('[leaks] traced memory grew by %d bytes over %d rounds' % (growth, rounds))
    return growth


def external_folders():
    """Read-only system folders with junctions, AppExecLinks or cloud placeholders, when present."""
    candidates = (
        ('user profile (junctions)', os.environ.get('USERPROFILE')),
        ('ProgramData (junctions)', os.environ.get('ProgramData')),
        ('WindowsApps (AppExecLink)', os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'WindowsApps')),
        ('OneDrive (cloud files)', os.environ.get('OneDrive')),
        ('System32', os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'System32')),
    )
    return [(label, path) for label, path in candidates if path and os.path.isdir(path)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--root', help='folder to create the cases in (default: a new temporary folder)')
    parser.add_argument('--keep', action='store_true', help='leave the folder in place afterwards')
    parser.add_argument('--native', help='path to _fsparser.pyd; default: import from the Core plug-in package')
    parser.add_argument('--no-external', action='store_true',
        help='skip the read-only system folders (user profile, ProgramData, WindowsApps, OneDrive, System32)')
    args = parser.parse_args(argv)
    if os.name != 'nt':
        parser.exit(2, 'Windows only\n')
    native = gauge.load_native(args.native)
    if native is None:
        parser.exit(2, 'Native module not found\n')

    root = args.root or tempfile.mkdtemp(prefix='fsparser-cases-')
    os.makedirs(root, exist_ok=True)
    problems = []
    try:
        cases = Cases(root)
        populate(cases)
        python_listing, batches = validate_folder(native, root, 'main folder', problems)
        missing = sorted(name for name in cases.entries if name not in python_listing.names)
        if missing:
            problems.append('created but not listed: %r' % missing)
        folder_counts = []
        for label, folder in cases.folders:
            listing, _ = validate_folder(native, folder, label, problems)
            folder_counts.append((label, len(listing.names)))
        if not args.no_external:
            for label, folder in external_folders():
                try:
                    # Live folders may change between the scan and os.stat; compare parsers only.
                    listing, _ = validate_folder(native, folder, label, problems, check_os=False)
                except (OSError, SystemExit) as error:
                    folder_counts.append((label, 'skipped: %s' % error))
                else:
                    folder_counts.append((label, len(listing.names)))
        check_synthetic(native, problems)
        check_contracts(native, problems)
        growth = check_leaks(native, problems)

        print('Folder: %s' % root)
        print('Entries listed: %d in %d batches' % (len(python_listing.names), len(batches)))
        for label, count in folder_counts:
            print('  %s: %s' % (label, count))
        print('Synthetic batches: %d valid sets, %d malformed; traced memory growth %d bytes' % (
            len(valid_synthetic_batches()), len(malformed_batches()), growth))
        print('Cases created: %d, skipped: %d' % (len(cases.created), len(cases.skipped)))
        for name, reason in sorted(cases.skipped.items()):
            print('  skipped %s - %s' % (name, reason))
        if problems:
            print('PROBLEMS (%d):' % len(problems))
            for problem in problems:
                print('  ' + problem)
        else:
            print('All native shapes, the native scan and os.stat agree with the Python parser.')
    finally:
        if not args.keep and not args.root:
            shutil.rmtree(extended(root), ignore_errors=True)
            if os.path.exists(root):
                subprocess.run(['cmd', '/c', 'rmdir', '/s', '/q', root], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
