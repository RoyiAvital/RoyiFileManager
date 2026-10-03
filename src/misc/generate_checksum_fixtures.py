"""Generate or verify the deterministic, public-data-only checksum corpus."""

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import struct
from dataclasses import dataclass
from zipfile import ZIP_STORED, ZipFile, ZipInfo


CORPUS_VERSION = 2
FIXED_TIMESTAMP = 946684800
WRITE_CHUNK = 64 * 1024
EMPTY_DIRECTORIES = ('empty folder', 'hierarchy/empty/nested')
REFERENCE_SUFFIXES = frozenset((
    '.sfv', '.md5', '.sha', '.sha1', '.sha224', '.sha256', '.sha384', '.sha512',
    '.blake3', '.bk3', '.sha3', '.sha3_224', '.sha3_256', '.sha3_384', '.sha3_512',
    '.sha3-224', '.sha3-256', '.sha3-384', '.sha3-512',
))


@dataclass(frozen=True)
class FixtureFile:
    path: str
    size: int
    pattern: bytes


def _literal(path, content):
    return FixtureFile(path, len(content), content or b'\x00')


def _stored_zip():
    stream = io.BytesIO()
    with ZipFile(stream, 'w', compression=ZIP_STORED) as archive:
        for name, content in (
            ('empty/', b''),
            ('nested/ascii.txt', b'Checksum fixture archive\n'),
            ('nested/caf\u00e9.txt', b'Unicode archive entry\n'),
            ('bytes.bin', bytes(range(256))),
        ):
            info = ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            info.create_system = 0
            info.compress_type = ZIP_STORED
            info.external_attr = 0x10 if name.endswith('/') else 0x20
            archive.writestr(info, content)
    return stream.getvalue()


def fixture_files():
    text = 'caf\u00e9 / \u0395\u03bb\u03bb\u03b7\u03bd\u03b9\u03ba\u03ac / \u65e5\u672c\u8a9e / \U00010437\n'
    png = base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAACXBIWXMAAA9hAAAPYQGoP6dp'
        'AAAADUlEQVQImWNgYPj/HwADAgH/xCAAOgAAAABJRU5ErkJggg=='
    )
    pcm = bytes(range(256)) * 4
    wave = (
        struct.pack('<4sI4s4sIHHIIHH4sI', b'RIFF', 36 + len(pcm), b'WAVE',
                    b'fmt ', 16, 1, 1, 8000, 8000, 1, 8, b'data', len(pcm))
        + pcm
    )
    files = [
        _literal('empty.dat', b''),
        _literal('text/ascii-lf.txt', b'first line\nsecond line\n'),
        _literal('text/ascii-crlf.txt', b'first line\r\nsecond line\r\n'),
        _literal('text/mixed-newlines.txt', b'LF\nCRLF\r\nCR\rend'),
        _literal('text/no-final-newline.txt', b'no final newline'),
        _literal('text/utf8.txt', text.encode('utf-8')),
        _literal('text/utf8-bom.txt', b'\xef\xbb\xbf' + text.encode('utf-8')),
        _literal('text/utf16-le.txt', b'\xff\xfe' + text.encode('utf-16-le')),
        _literal('text/utf16-be.txt', b'\xfe\xff' + text.encode('utf-16-be')),
        _literal('text/utf32-le.txt', b'\xff\xfe\x00\x00' + text.encode('utf-32-le')),
        _literal('binary/all-byte-values.bin', bytes(range(256))),
        _literal('binary/one-nul.bin', b'\x00'),
        _literal('binary/one-ff.bin', b'\xff'),
        _literal('binary/embedded-controls.bin', b'before\x00\x01\x1a\x7f\xffafter'),
        _literal('formats/sample.json', b'{"fixture":1,"values":[null,true,0]}\n'),
        _literal('formats/sample.csv', b'name,value\r\n"comma,name",1\r\n'),
        _literal('formats/one-pixel.png', png),
        _literal('formats/sample.wav', wave),
        _literal('formats/stored.zip', _stored_zip()),
        _literal('names/no_extension', b'no extension\n'),
        _literal('names/.dotfile', b'dotfile, not a Windows hidden attribute\n'),
        _literal('names/ leading space.txt', b'leading space in basename\n'),
        _literal('names/two  spaces.txt', b'two spaces in basename\n'),
        _literal('names/-leading-dash.txt', b'not a command option\n'),
        _literal('names/;semicolon.txt', b'not an SFV header\n'),
        _literal('names/#hash [brackets] (parentheses).txt', b'punctuation\n'),
        _literal('names/percent%20 literal.txt', b'not URL-encoded\n'),
        _literal("names/ampersand & dollar $ apostrophe '.txt", b'not shell syntax\n'),
        _literal('hierarchy/left/repeated.txt', b'left\n'),
        _literal('hierarchy/right/repeated.txt', b'right\n'),
        _literal('hierarchy/level 1/level 2/level 3/repeated.txt', b'deep\n'),
        _literal('unicode/nfc/caf\u00e9.txt', b'precomposed filename\n'),
        _literal('unicode/nfd/cafe\u0301.txt', b'decomposed filename\n'),
        _literal('unicode/\u0395\u03bb\u03bb\u03b7\u03bd\u03b9\u03ba\u03ac/\u03b4\u03bf\u03ba\u03b9\u03bc\u03ae.txt', b'Greek names\n'),
        _literal('unicode/\u041a\u0438\u0440\u0438\u043b\u043b\u0438\u0446\u0430/\u0442\u0435\u0441\u0442.txt', b'Cyrillic names\n'),
        _literal('unicode/\u65e5\u672c\u8a9e/\u8cc7\u6599.txt', b'Japanese names\n'),
        _literal('unicode/\u4e2d\u6587/\u6d4b\u8bd5.txt', b'Chinese names\n'),
        _literal('unicode/\ud55c\uae00/\uc2dc\ud5d8.txt', b'Korean names\n'),
        _literal('unicode/\u05e2\u05d1\u05e8\u05d9\u05ea/\u05d1\u05d3\u05d9\u05e7\u05d4.txt', b'Hebrew names\n'),
        _literal('unicode/\u0639\u0631\u0628\u064a/\u0627\u062e\u062a\u0628\u0627\u0631.txt', b'Arabic names\n'),
        _literal('unicode/supplementary-\U00010437/music-\U0001d11e.txt', b'Non-BMP names\n'),
    ]
    root_samples = (
        'text/ascii-lf.txt', 'text/ascii-crlf.txt', 'text/utf8.txt', 'text/utf8-bom.txt',
        'names/no_extension', 'names/.dotfile', 'names/ leading space.txt',
        'names/two  spaces.txt', 'names/-leading-dash.txt', 'names/;semicolon.txt',
        'names/#hash [brackets] (parentheses).txt', 'names/percent%20 literal.txt',
        "names/ampersand & dollar $ apostrophe '.txt", 'unicode/nfc/caf\u00e9.txt',
        'unicode/nfd/cafe\u0301.txt', 'unicode/\u65e5\u672c\u8a9e/\u8cc7\u6599.txt',
        'unicode/\u05e2\u05d1\u05e8\u05d9\u05ea/\u05d1\u05d3\u05d9\u05e7\u05d4.txt',
        'unicode/supplementary-\U00010437/music-\U0001d11e.txt',
        'binary/all-byte-values.bin', 'formats/one-pixel.png', 'formats/sample.wav',
        'formats/stored.zip', 'formats/sample.json', 'formats/sample.csv', 'binary/one-nul.bin',
    )
    sources = {entry.path: entry for entry in files}
    files.extend(FixtureFile(PurePosixPath(path).name, sources[path].size,
                             sources[path].pattern) for path in root_samples)
    sizes = (63, 64, 65, 135, 136, 137, 1023, 1024, 1025, 2047, 2048, 2049,
             4 * 1024 * 1024 - 1, 4 * 1024 * 1024, 4 * 1024 * 1024 + 1,
             16 * 1024 * 1024 + 1)
    files.extend(FixtureFile(f'boundaries/bytes-{size:08d}.bin', size,
                             bytes(range(256))) for size in sizes)
    deep = '/'.join(f'level-{index:02d}-' + 'x' * 24 for index in range(8))
    files.append(_literal('long-path/' + deep + '/end.txt', b'Beyond MAX_PATH\n'))
    return tuple(sorted(files, key=lambda entry: entry.path))


def fixture_directories():
    directories = set(EMPTY_DIRECTORIES)
    for entry in fixture_files():
        directories.update(str(parent) for parent in PurePosixPath(entry.path).parents
                           if str(parent) != '.')
    for directory in EMPTY_DIRECTORIES:
        directories.update(str(parent) for parent in PurePosixPath(directory).parents
                           if str(parent) != '.')
    return tuple(sorted(directories, key=lambda path: (len(PurePosixPath(path).parts), path)))


def _chunks(entry):
    block = entry.pattern * max(1, WRITE_CHUNK // len(entry.pattern))
    remaining = entry.size
    while remaining:
        chunk = block[:min(remaining, len(block))]
        yield chunk
        remaining -= len(chunk)


def _native_path(path):
    absolute = os.path.abspath(os.fspath(path))
    if os.name != 'nt' or absolute.startswith('\\\\?\\'):
        return Path(absolute)
    if absolute.startswith('\\\\'):
        return Path('\\\\?\\UNC\\' + absolute[2:])
    return Path('\\\\?\\' + absolute)


def _is_redirected(path):
    metadata = path.lstat()
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, 'st_file_attributes', 0)
        & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
    )


def generate(destination):
    root = _native_path(destination)
    if root.exists():
        if _is_redirected(root) or not root.is_dir():
            raise ValueError('Destination must be an ordinary directory.')
        if any(root.iterdir()):
            raise ValueError('Destination must be empty; nothing was changed.')
    else:
        root.mkdir(parents=True)
    directories = fixture_directories()
    for directory in directories:
        (root / directory).mkdir()
    for entry in fixture_files():
        target = root / entry.path
        with target.open('xb') as output:
            for chunk in _chunks(entry):
                output.write(chunk)
        os.utime(target, (FIXED_TIMESTAMP, FIXED_TIMESTAMP))
    for directory in reversed(directories):
        os.utime(root / directory, (FIXED_TIMESTAMP, FIXED_TIMESTAMP))
    return inventory()


def inventory():
    records = []
    for entry in fixture_files():
        digest = hashlib.sha256()
        for chunk in _chunks(entry):
            digest.update(chunk)
        records.append({'path': entry.path, 'size': entry.size, 'sha256': digest.hexdigest()})
    return {'version': CORPUS_VERSION, 'directories': sorted(fixture_directories()),
            'files': records}


def corpus_id():
    encoded = json.dumps(inventory(), ensure_ascii=True, sort_keys=True,
                         separators=(',', ':')).encode('ascii')
    return hashlib.sha256(encoded).hexdigest()


def verify(destination):
    root = _native_path(destination)
    if _is_redirected(root):
        raise ValueError('Fixture root must not be redirected.')
    expected = inventory()
    expected_paths = {entry['path'] for entry in expected['files']}
    actual_files, actual_directories = set(), set()
    for current, directories, filenames in os.walk(root, followlinks=False):
        for name in directories + filenames:
            target = Path(current) / name
            if _is_redirected(target):
                raise ValueError('Redirected fixture entry: ' + ascii(str(target)))
            relative = target.relative_to(root).as_posix()
            if (name in filenames and target.parent == root and relative not in expected_paths
                    and target.suffix.lower() in REFERENCE_SUFFIXES):
                continue
            (actual_directories if name in directories else actual_files).add(relative)
    if actual_files != expected_paths:
        raise ValueError('Fixture file list differs from the versioned corpus.')
    if actual_directories != set(expected['directories']):
        raise ValueError('Fixture directory list differs from the versioned corpus.')
    for entry in expected['files']:
        target = root / entry['path']
        if target.stat().st_size != entry['size']:
            raise ValueError('Fixture size differs: ' + ascii(entry['path']))
        digest = hashlib.sha256()
        with target.open('rb') as source:
            while chunk := source.read(WRITE_CHUNK):
                digest.update(chunk)
        if digest.hexdigest() != entry['sha256']:
            raise ValueError('Fixture bytes differ: ' + ascii(entry['path']))
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--verify', action='store_true',
                        help='Verify the corpus without changing it; allow root-level checksum manifests.')
    arguments = parser.parse_args()
    try:
        result = verify(arguments.destination) if arguments.verify else generate(arguments.destination)
    except (OSError, ValueError) as error:
        parser.exit(1, ascii(str(error)) + '\n')
    print(f"Corpus v{CORPUS_VERSION}: {len(result['files'])} files, "
          f"{sum(entry['size'] for entry in result['files'])} bytes")
    print('Corpus SHA256:', corpus_id())
    print('Verified.' if arguments.verify else
          'Generated directly in the destination. Exclude existing checksum manifests from TC selections.')


if __name__ == '__main__':
    main()