"""Source/binary pairing of _fsenum.pyd (Done/DirectoryEnumerator001.md).

The source digest covers every file that shapes the binary: the manifest and
lock file, the build helper, the Unicode generator and every Rust source.
Each file is hashed by its relative path and its bytes with CRLF normalised to
LF, so Git line-ending conversion cannot change it. The binary is hashed byte
for byte. The sidecar `fsenum.sha256` is plain text.
"""

import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
BINARY = HERE / '_fsenum.pyd'
SIDECAR = HERE / 'fsenum.sha256'
LFS_POINTER_PREFIX = b'version https://git-lfs.github.com/spec/v1'


def source_files():
	files = [HERE / name for name in ('Cargo.toml', 'Cargo.lock', 'build_fsenum.py', 'generate_unicode.py')]
	return files + sorted((HERE / 'src').glob('*.rs'))


def source_hash():
	digest = hashlib.sha256()
	for path in source_files():
		digest.update(path.relative_to(HERE).as_posix().encode('utf-8') + b'\0')
		digest.update(path.read_bytes().replace(b'\r\n', b'\n') + b'\0')
	return digest.hexdigest()


def binary_hash(path=BINARY):
	return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def is_lfs_pointer(path):
	with open(path, 'rb') as handle:
		return handle.read(len(LFS_POINTER_PREFIX)) == LFS_POINTER_PREFIX


def write_hashes():
	source, binary = source_hash(), binary_hash()
	text = (
		'# SHA-256 pairing of the fsenum sources (fsenum_hashes.py) and _fsenum.pyd (raw bytes).\n'
		'# Written by build_fsenum.py; checked by check_hashes.py.\n'
		'source %s\n'
		'binary %s\n' % (source, binary)
	)
	SIDECAR.write_text(text, encoding='ascii', newline='\n')
	return source, binary


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


def check():
	"""Return a list of problems; empty when the pairing holds."""
	for path in source_files() + [BINARY, SIDECAR]:
		if not path.is_file():
			return ['Missing %s' % path]
	try:
		expected_source, expected_binary = read_sidecar()
	except (ValueError, UnicodeDecodeError) as error:
		return ['Unreadable sidecar: %s' % error]
	problems = []
	actual_source = source_hash()
	if actual_source != expected_source:
		problems.append('fsenum sources changed since the binary was built (%s, recorded %s): '
			'run build_fsenum.py' % (actual_source[:12], expected_source[:12]))
	if is_lfs_pointer(BINARY):
		problems.append('_fsenum.pyd is a Git LFS pointer, not the module: run `git lfs pull`')
	elif binary_hash() != expected_binary:
		problems.append('_fsenum.pyd does not match the recorded build (%s, recorded %s)'
			% (binary_hash()[:12], expected_binary[:12]))
	return problems
