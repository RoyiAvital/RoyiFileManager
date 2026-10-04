"""Shared hashing for the `_fsparser` source/binary pairing (Done/FSParser.md).

The C source is hashed with CRLF normalised to LF, so a checkout with Git
line-ending conversion produces the same digest as the original. The binary is
hashed byte for byte. The sidecar `fsparser.sha256` is plain text and is read
tolerant of either line ending.
"""

import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'fsparser.c'
BINARY = HERE / '_fsparser.pyd'
SIDECAR = HERE / 'fsparser.sha256'
LFS_POINTER_PREFIX = b'version https://git-lfs.github.com/spec/v1'


def source_hash(path=SOURCE):
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def binary_hash(path=BINARY):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def is_lfs_pointer(path):
    with open(path, 'rb') as handle:
        return handle.read(len(LFS_POINTER_PREFIX)) == LFS_POINTER_PREFIX


def write_sidecar(source, binary, path=SIDECAR):
    text = (
        '# SHA-256 pairing of fsparser.c (CRLF normalised to LF) and _fsparser.pyd (raw bytes).\n'
        '# Regenerate with write_hashes.py after rebuilding; check with check_hashes.py.\n'
        'source %s\n'
        'binary %s\n' % (source, binary)
    )
    Path(path).write_text(text, encoding='ascii', newline='\n')


def read_sidecar(path=SIDECAR):
    values = {}
    for line in Path(path).read_text(encoding='ascii').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, _, value = line.partition(' ')
        values[key] = value.strip().lower()
    missing = {'source', 'binary'} - values.keys()
    if missing:
        raise ValueError('%s lacks %s' % (path, ', '.join(sorted(missing))))
    return values['source'], values['binary']
