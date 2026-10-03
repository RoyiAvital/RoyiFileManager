"""Streaming checksum manifests; no host or Qt dependencies."""

from dataclasses import dataclass
import hashlib
import ntpath
import os
import re
import stat
import sys
import tempfile
import time
import zlib


@dataclass(frozen=True)
class Algorithm:
    identifier: str
    label: str
    extension: str
    hex_length: int


ALGORITHMS = (
    Algorithm('crc32', 'CRC32 (SFV)', '.sfv', 8),
    Algorithm('md5', 'MD5', '.md5', 32),
    Algorithm('blake3', 'BLAKE3', '.blake3', 64),
    Algorithm('sha1', 'SHA1', '.sha', 40),
    Algorithm('sha224', 'SHA224', '.sha224', 56),
    Algorithm('sha256', 'SHA256', '.sha256', 64),
    Algorithm('sha384', 'SHA384', '.sha384', 96),
    Algorithm('sha512', 'SHA512', '.sha512', 128),
    Algorithm('sha3_224', 'SHA3_224', '.sha3_224', 56),
    Algorithm('sha3_256', 'SHA3_256', '.sha3_256', 64),
    Algorithm('sha3_384', 'SHA3_384', '.sha3_384', 96),
    Algorithm('sha3_512', 'SHA3_512', '.sha3_512', 128),
)
BY_ID = {algorithm.identifier: algorithm for algorithm in ALGORITHMS}
BY_EXTENSION = {algorithm.extension: algorithm for algorithm in ALGORITHMS}
BY_EXTENSION.update({'.sha1': BY_ID['sha1'], '.bk3': BY_ID['blake3'], '.sha3': BY_ID['sha3_256']})
BY_EXTENSION.update({'.sha3-' + str(bits): BY_ID['sha3_' + str(bits)] for bits in (224, 256, 384, 512)})
UNSUPPORTED_EXTENSIONS = frozenset(('.xxh', '.xxh3', '.xxh128', '.blake2', '.blake2s', '.blake2b'))
MAX_RECORD_BYTES = 256 * 1024


@dataclass(frozen=True)
class Settings:
    default_algorithm: str = 'sha256'
    filename_encoding: str = 'utf-8-sig'
    unix_format: bool = False
    chunk_size_mib: int = 4
    blake3_threads: int = 0

    @classmethod
    def from_mapping(cls, values):
        if not isinstance(values, dict):
            raise ValueError('ChecksumFiles settings must be a JSON object.')
        settings = cls(**{name: values.get(name, field.default)
                          for name, field in cls.__dataclass_fields__.items()})
        if not isinstance(settings.default_algorithm, str) or settings.default_algorithm not in BY_ID:
            raise ValueError('Unsupported default_algorithm.')
        if settings.filename_encoding not in ('utf-8', 'utf-8-sig'):
            raise ValueError('filename_encoding must be utf-8 or utf-8-sig.')
        if type(settings.unix_format) is not bool:
            raise ValueError('unix_format must be true or false.')
        for name, lower, upper in (('chunk_size_mib', 1, 64), ('blake3_threads', 0, 16)):
            value = getattr(settings, name)
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError('%s must be an integer from %s to %s.' % (name, lower, upper))
        return settings

    @property
    def encoding(self):
        return 'utf-8' if self.unix_format else self.filename_encoding

    @property
    def newline(self):
        return '\n' if self.unix_format else '\r\n'


@dataclass(frozen=True)
class Record:
    path: str
    digest: str


def algorithm_for_path(path):
    extension = ntpath.splitext(os.fspath(path))[1].lower()
    try:
        return BY_EXTENSION[extension]
    except KeyError:
        raise ValueError('Unsupported checksum file extension: ' + extension) from None


def relative_path(value):
    if not isinstance(value, str) or not value or ntpath.splitdrive(value)[0] or value[0] in '/\\':
        raise ValueError('Expected a relative file path.')
    parts = value.replace('\\', '/').split('/')
    clean = []
    for part in parts:
        if part == '.':
            continue
        if (not part or part == '..' or part.endswith((' ', '.'))
                or any(ord(character) < 32 or character in '<>:"|?*' for character in part)
            or ntpath.isreserved(part)):
            raise ValueError('Unsafe or unsupported file path.')
        try:
            part.encode('utf-8')
        except UnicodeEncodeError:
            raise ValueError('Invalid Unicode in file path.') from None
        clean.append(part)
    if not clean:
        raise ValueError('Empty file path.')
    return '/'.join(clean)


def native_path(path):
    value = os.path.abspath(os.fspath(path))
    if os.name != 'nt' or value.startswith('\\\\?\\'):
        return value
    return '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value


def parse_record(line, algorithm):
    text = line.removesuffix('\n').removesuffix('\r')
    if not text:
        return None
    if algorithm.identifier == 'crc32':
        match = re.fullmatch(r'(.+) ([0-9A-Fa-f]{8})', text)
        if match is None:
            if text.startswith(';'):
                return None
            raise ValueError('Malformed SFV record.')
        path, digest = match.groups()
    else:
        match = re.fullmatch(r'([0-9A-Fa-f]{%d}) (?:\*| )(.+)' % algorithm.hex_length, text)
        if match is None:
            raise ValueError('Malformed %s record.' % algorithm.label)
        digest, path = match.groups()
    return Record(relative_path(path), digest.lower())


def format_record(path, digest, algorithm, settings):
    normalized = relative_path(path)
    if not re.fullmatch(r'[0-9A-Fa-f]{%d}' % algorithm.hex_length, digest):
        raise ValueError('Invalid checksum digest.')
    name = normalized if settings.unix_format else normalized.replace('/', '\\')
    if algorithm.identifier == 'crc32':
        line = name + ' ' + digest.upper()
    else:
        line = digest.lower() + ('  ' if algorithm.identifier == 'blake3' else ' *') + name
    encoded = (line + settings.newline).encode('utf-8')
    if len(encoded) > MAX_RECORD_BYTES:
        raise ValueError('Checksum record exceeds the 256 KiB limit.')
    return line + settings.newline


class Canceled(Exception):
    pass


class ChangedFile(OSError):
    pass


class LinkedPath(OSError):
    pass


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _inspect(path, info=None):
    info = os.lstat(native_path(path)) if info is None else info
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x441400:
        raise LinkedPath('Links, reparse points and offline placeholders are not followed.')
    return info


def _check_chain(root, path, checked=None, check=lambda: None):
    parents = []
    current = os.path.abspath(path)
    _relative(root, current)
    while current != root:
        check()
        if checked is not None and current in checked:
            break
        parents.append(current)
        current = os.path.dirname(current)
    for parent in reversed(parents):
        check()
        info = _inspect(parent)
        if checked is not None and stat.S_ISDIR(info.st_mode) and len(checked) < 256:
            checked.add(parent)


def _relative(root, path):
    absolute = os.path.abspath(path)
    if absolute != root and not absolute.startswith(root.rstrip(os.sep) + os.sep):
        raise ValueError('Input is outside the captured folder.')
    return os.path.relpath(absolute, root)


def _native_blake3():
    try:
        try:
            from ._vendor.blake3 import blake3
        except ModuleNotFoundError as error:
            if getattr(sys, 'frozen', False) or error.name != __package__ + '._vendor':
                raise
            from blake3 import blake3
    except ImportError as error:
        raise ValueError('The BLAKE3 dependency is missing or incompatible. Restore the bundled native dependency, or the blake3 package in the source environment.') from error
    return blake3


class HashState:
    def __init__(self, settings):
        self.buffer = bytearray(settings.chunk_size_mib * 1024 * 1024)
        self.blake3 = {}


def _hasher(algorithm, settings, size, state):
    if algorithm.identifier == 'crc32':
        return None
    if algorithm.identifier == 'blake3':
        threads = settings.blake3_threads
        if size < 16 * 1024 * 1024:
            threads = 1
        elif threads == 0:
            threads = min(4, max(1, (os.cpu_count() or 1) - 1))
        if threads not in state.blake3:
            state.blake3[threads] = _native_blake3()(max_threads=threads)
        digest = state.blake3[threads]
        digest.reset()
        return digest
    return hashlib.new(algorithm.identifier, usedforsecurity=False)


def hash_file(path, algorithm, settings, check=lambda: None, progress=lambda amount: None, state=None):
    check()
    initial = _inspect(path)
    if not stat.S_ISREG(initial.st_mode):
        raise OSError('Not a regular file.')
    state = state if state is not None else HashState(settings)
    view = memoryview(state.buffer)
    count = 0
    checksum = 0
    with open(native_path(path), 'rb') as source:
        before = os.fstat(source.fileno())
        if _identity(initial) != _identity(before):
            raise ChangedFile('File changed before reading.')
        digest = _hasher(algorithm, settings, before.st_size, state)
        while True:
            check()
            amount = source.readinto(state.buffer)
            if not amount:
                break
            if digest is None:
                checksum = zlib.crc32(view[:amount], checksum)
            else:
                digest.update(view[:amount])
            count += amount
            progress(amount)
        check()
        after = os.fstat(source.fileno())
    current = _inspect(path)
    if _identity(before) != _identity(after) or _identity(before) != _identity(current) or count != before.st_size:
        raise ChangedFile('File changed while reading.')
    return ('%08x' % (checksum & 0xffffffff) if digest is None else digest.hexdigest()), count


def _roots(root, selected):
    candidates = {}
    for path in selected or (root,):
        absolute = os.path.abspath(path)
        _relative(root, absolute)
        candidates[absolute] = None
    roots = []
    for path in candidates:
        parent = path
        while parent != root:
            parent = os.path.dirname(parent)
            if parent in candidates:
                break
        else:
            roots.append(path)
    return tuple(roots)


def _walk_files(root, selected, check, skipped):
    for chosen in _roots(root, selected):
        check()
        try:
            _check_chain(root, chosen, check=check)
            info = os.stat(native_path(chosen)) if chosen == root else _inspect(chosen)
        except LinkedPath:
            skipped(os.path.relpath(chosen, root))
            continue
        if stat.S_ISREG(info.st_mode):
            yield chosen
            continue
        if not stat.S_ISDIR(info.st_mode):
            skipped(os.path.relpath(chosen, root))
            continue
        stack = [os.scandir(native_path(chosen))]
        try:
            while stack:
                check()
                entry = next(stack[-1], None)
                if entry is None:
                    stack.pop().close()
                    continue
                try:
                    info = _inspect(entry.path, entry.stat(follow_symlinks=False))
                except LinkedPath:
                    skipped(entry.path)
                    continue
                if stat.S_ISDIR(info.st_mode):
                    stack.append(os.scandir(native_path(entry.path)))
                elif stat.S_ISREG(info.st_mode):
                    yield entry.path
                else:
                    skipped(entry.path)
        finally:
            for iterator in stack:
                iterator.close()


def _logical(path):
    if path.startswith('\\\\?\\UNC\\'):
        return '\\\\' + path[8:]
    return path[4:] if path.startswith('\\\\?\\') else path


def _existing_destination_path(path):
    if os.name != 'nt':
        return path
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    create.restype = wintypes.HANDLE
    final_path = kernel.GetFinalPathNameByHandleW
    final_path.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD)
    final_path.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    share_read_write_delete = 7
    open_existing = 3
    open_reparse_point = 0x00200000
    handle = create(native_path(path), 0, share_read_write_delete, None, open_existing, open_reparse_point, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = final_path(handle, buffer, len(buffer), 0)
        if not length:
            raise ctypes.WinError(ctypes.get_last_error())
        if length >= len(buffer):
            raise OSError('Destination name exceeds the Windows path limit.')
        return os.path.join(os.path.dirname(path), ntpath.basename(buffer.value))
    finally:
        kernel.CloseHandle(handle)


@dataclass(frozen=True)
class GenerationResult:
    files: int
    bytes_read: int
    skipped: int


def generate(root, selected, destination, algorithm, settings, check=lambda: None,
             progress=lambda amount: None, expected_destination=None):
    check()
    root = os.path.abspath(root)
    destination = os.path.abspath(destination)
    relative_path(_relative(root, destination))
    _check_chain(root, os.path.dirname(destination), check=check)
    try:
        existing = _inspect(destination)
    except FileNotFoundError:
        existing = None
    if existing is not None and (expected_destination is None or _identity(existing) != expected_destination):
        raise ChangedFile('Destination already exists or changed since confirmation.')
    if existing is None and expected_destination is not None:
        raise ChangedFile('Destination disappeared since confirmation.')
    excluded_destination = _existing_destination_path(destination) if existing is not None else destination
    check()
    state = HashState(settings)
    descriptor, staging = tempfile.mkstemp(prefix='.checksum-', suffix='.tmp', dir=native_path(os.path.dirname(destination)))
    files = size = skipped = 0

    def note_skip(path):
        nonlocal skipped
        skipped += 1

    try:
        with os.fdopen(descriptor, 'w', encoding=settings.encoding, newline='') as output:
            if algorithm.identifier == 'crc32':
                output.write('; ChecksumFiles' + settings.newline)
            for path in _walk_files(root, selected, check, note_skip):
                logical = _logical(path)
                if logical in (excluded_destination, _logical(staging)):
                    continue
                relative = relative_path(_relative(root, logical))
                digest, amount = hash_file(path, algorithm, settings, check, progress, state)
                output.write(format_record(relative, digest, algorithm, settings))
                files += 1
                size += amount
            if not files:
                raise ValueError('No eligible files found; no checksum file was written.')
            output.flush()
        check()
        try:
            current = _inspect(destination)
        except FileNotFoundError:
            current = None
        if (None if current is None else _identity(current)) != expected_destination:
            raise ChangedFile('Destination changed before publication.')
        _check_chain(root, os.path.dirname(destination), check=check)
        check()
        os.replace(native_path(staging), native_path(destination))
        return GenerationResult(files, size, skipped)
    finally:
        try:
            os.unlink(native_path(staging))
        except FileNotFoundError:
            pass


def discover(root, check=lambda: None):
    check()
    found = []
    with os.scandir(native_path(root)) as entries:
        for entry in entries:
            check()
            if ntpath.splitext(entry.name)[1].lower() in BY_EXTENSION or ntpath.splitext(entry.name)[1].lower() in UNSUPPORTED_EXTENSIONS:
                try:
                    info = _inspect(entry.path, entry.stat(follow_symlinks=False))
                except LinkedPath:
                    continue
                if stat.S_ISREG(info.st_mode):
                    found.append(_logical(entry.path))
    return tuple(sorted(found))


def display_text(value, limit=4096):
    text = str(value)
    safe = ''.join(character if character.isprintable() else ascii(character)[1:-1] for character in text[:limit])
    return safe if len(safe) <= limit and len(text) <= limit else safe[:limit - 3] + '...'


@dataclass(frozen=True)
class ResultRow:
    line: int
    path: str
    status: str
    expected: str = ''
    actual: str = ''
    details: str = ''
    target: str | None = None

    @property
    def cells(self):
        return tuple(display_text(value) for value in (self.path, self.status, self.expected, self.actual, self.details))

    @property
    def display_bytes(self):
        return len(str(self.line)) + sum(len(value.encode('utf-8')) for value in self.cells)

    @property
    def payload_bytes(self):
        return self.display_bytes + self.raw_bytes

    @property
    def raw_bytes(self):
        return sum(len(value.encode('utf-8', 'surrogatepass')) for value in (self.path, self.details, self.target or ''))


class Results:
    def __init__(self, row_limit=9999, byte_limit=16 * 1024 * 1024 - 65536, payload_limit=32 * 1024 * 1024):
        self.row_limit = row_limit
        self.byte_limit = byte_limit
        self.payload_limit = payload_limit
        self.total = self.matched = self.bytes_read = 0
        self.problems = []
        self.all_rows = []
        self._problem_bytes = self._all_bytes = self._problem_payload = self._all_payload = 0
        self._problems_full = False
        self.complete = False
        self.reason = ''

    def add(self, row):
        self.total += 1
        self.matched += row.status == 'Matched'
        if len(self.problems) >= self.row_limit:
            self._problems_full = True
        if self.all_rows is not None and len(self.all_rows) >= self.row_limit:
            self.all_rows = None
        if self.all_rows is None and (self._problems_full or row.status == 'Matched'):
            return
        size = row.display_bytes
        payload = size + row.raw_bytes
        if row.status != 'Matched' and not self._problems_full:
            if self._problem_bytes + size > self.byte_limit or self._problem_payload + payload > self.payload_limit:
                self._problems_full = True
            else:
                self.problems.append(row)
                self._problem_bytes += size
                self._problem_payload += payload
        if self.all_rows is not None:
            if self._all_bytes + size > self.byte_limit or self._all_payload + payload > self.payload_limit:
                self.all_rows = None
            else:
                self.all_rows.append(row)
                self._all_bytes += size
                self._all_payload += payload

    def freeze(self):
        self.problems = tuple(self.problems)
        if self.all_rows is not None:
            self.all_rows = tuple(self.all_rows)
        return self

    @property
    def summary(self):
        state = 'All matched' if self.complete and self.total and self.total == self.matched else 'Completed' if self.complete else 'Incomplete'
        omitted = self.total - self.matched - len(self.problems)
        message = '%s: %s matched, %s problems, %s bytes read.' % (state, self.matched, self.total - self.matched, self.bytes_read)
        if self.reason:
            message += ' ' + display_text(self.reason)
        if omitted:
            message += ' Results truncated; %s problem rows omitted.' % omitted
        if self.all_rows is None:
            message += ' Showing problems only: display limit exceeded.'
        return message


def verify(manifest, settings, check=lambda: None, progress=lambda amount: None,
           results=None, duplicate_limit=16 * 1024 * 1024):
    results = results if results is not None else Results()

    def report_read(amount):
        results.bytes_read += amount
        progress(amount)

    seen = set()
    key_bytes = 0
    parent = os.path.dirname(os.path.abspath(manifest))
    checked = set()
    line_number = 0
    try:
        check()
        algorithm = algorithm_for_path(manifest)
        state = HashState(settings)
        _check_chain(parent, manifest, checked, check)
        original = _inspect(manifest)
        if not stat.S_ISREG(original.st_mode):
            raise OSError('Manifest is not a regular file.')
        with open(native_path(manifest), 'rb') as source:
            before = os.fstat(source.fileno())
            if _identity(before) != _identity(original):
                raise ChangedFile('Manifest changed before reading.')
            while True:
                check()
                raw = source.readline(MAX_RECORD_BYTES + 1)
                if not raw:
                    break
                line_number += 1
                if len(raw) > MAX_RECORD_BYTES:
                    while not raw.endswith(b'\n'):
                        check()
                        raw = source.readline(MAX_RECORD_BYTES + 1)
                        if not raw:
                            break
                    results.add(ResultRow(line_number, '', 'Invalid record', details='Record exceeds 256 KiB.'))
                    continue
                text = ''
                try:
                    text = raw.decode('utf-8-sig' if line_number == 1 else 'utf-8')
                    record = parse_record(text, algorithm)
                    if record is None:
                        continue
                except (ValueError, UnicodeError) as error:
                    results.add(ResultRow(line_number, text, 'Invalid record', details=str(error)))
                    continue
                key = record.path
                if key in seen:
                    results.add(ResultRow(line_number, key, 'Duplicate', record.digest, details='Duplicate normalized path.'))
                    continue
                key_bytes += len(key.encode('utf-8'))
                if key_bytes > duplicate_limit:
                    results.reason = 'Duplicate-path bookkeeping limit exceeded.'
                    return results.freeze()
                seen.add(key)
                path = os.path.join(parent, *key.split('/'))
                try:
                    _check_chain(parent, path, checked, check)
                    actual, amount = hash_file(path, algorithm, settings, check, report_read, state)
                    status = 'Matched' if actual == record.digest else 'Mismatch'
                    row = ResultRow(line_number, key, status, record.digest, actual, target=path)
                except FileNotFoundError as error:
                    row = ResultRow(line_number, key, 'Missing', record.digest, details=str(error))
                except LinkedPath as error:
                    row = ResultRow(line_number, key, 'Skipped: link', record.digest, details=str(error))
                except ChangedFile as error:
                    row = ResultRow(line_number, key, 'Changed', record.digest, details=str(error))
                except OSError as error:
                    row = ResultRow(line_number, key, 'Unreadable', record.digest, details=str(error))
                results.add(row)
            after = os.fstat(source.fileno())
        if _identity(before) != _identity(after) or _identity(before) != _identity(_inspect(manifest)):
            raise ChangedFile('Manifest changed while reading.')
        check()
        results.complete = True
        if not results.total:
            results.reason = 'No checksum records found.'
    except Canceled:
        results.reason = 'Canceled.'
    except (OSError, ValueError) as error:
        results.reason = str(error)
    return results.freeze()


class Progress:
    def __init__(self, callback):
        self.callback = callback
        self.bytes_read = 0
        self._last = 0

    def __call__(self, amount):
        self.bytes_read += amount
        now = time.monotonic()
        if now - self._last >= 0.1:
            self._last = now
            self.callback(self.bytes_read)