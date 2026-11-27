"""Build _fsenum.pyd with the pinned Rust toolchain and record its hashes.

    python src/main/rust/fsenum/build_fsenum.py [--test] [--no-record]

Uses the toolchain's self-contained MinGW linker and runtime
(`-C link-self-contained=yes`), so no other compiler on PATH is involved and
the module imports only system DLLs and python3.dll. The linker writes no
build time into the module, so the same sources give the same binary.
Refuses another rustc release than RUSTC_RELEASE; see README.md. `--test` runs
`cargo test` first. Unless `--no-record`, copies the module to _fsenum.pyd and
writes fsenum.sha256.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fsenum_hashes import BINARY, write_hashes  # noqa: E402

RUSTC_RELEASE = '1.99.1'
TARGET = 'x86_64-pc-windows-gnu'
EXPECTED_IMPORTS = {'python3.dll', 'kernel32.dll', 'msvcrt.dll', 'ntdll.dll',
	'api-ms-win-core-synch-l1-2-0.dll'}


def toolchain_environment():
	version = subprocess.run(['rustc', '-vV'], check=True, capture_output=True, text=True).stdout
	fields = dict(line.split(': ', 1) for line in version.splitlines() if ': ' in line)
	if fields.get('release') != RUSTC_RELEASE or fields.get('host') != TARGET:
		raise SystemExit('Requires rustc %s on %s; found %s on %s' % (
			RUSTC_RELEASE, TARGET, fields.get('release'), fields.get('host')))
	sysroot = Path(subprocess.run(['rustc', '--print', 'sysroot'], check=True, capture_output=True,
		text=True).stdout.strip())
	linker = sysroot / 'lib' / 'rustlib' / TARGET / 'bin' / 'self-contained' / 'x86_64-w64-mingw32-gcc.exe'
	if not linker.is_file():
		raise SystemExit('The rust-mingw component is missing: %s' % linker)
	environment = os.environ.copy()
	environment['CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER'] = str(linker)
	# With the rust-src component, rustc names standard library sources by their local
	# path in panic locations; the rustup folder would then change the binary.
	library = sysroot / 'lib/rustlib/src/rust'
	flags = ['-C', 'link-self-contained=yes', '-C', 'link-arg=-Wl,--no-insert-timestamp',
		'--remap-path-prefix=%s=/rustc/%s' % (library, fields['commit-hash'])]
	environment.pop('RUSTFLAGS', None)
	environment['CARGO_ENCODED_RUSTFLAGS'] = '\x1f'.join(flags)
	environment['CARGO_TARGET_DIR'] = str(HERE.parents[3] / 'target' / 'fsenum')
	return environment


def imports(path):
	import pefile
	module = pefile.PE(str(path), fast_load=True)
	module.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
	return {entry.dll.decode('ascii').lower() for entry in module.DIRECTORY_ENTRY_IMPORT}


def main(argv=None):
	parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
	parser.add_argument('--test', action='store_true', help='run cargo test first')
	parser.add_argument('--no-record', action='store_true', help='build only; leave _fsenum.pyd and hashes')
	args = parser.parse_args(argv)
	environment = toolchain_environment()
	manifest = str(HERE / 'Cargo.toml')
	if args.test:
		subprocess.run(['cargo', 'test', '--release', '--locked', '--offline', '--manifest-path', manifest],
			check=True, env=environment)
	subprocess.run(['cargo', 'build', '--release', '--locked', '--offline', '--manifest-path', manifest],
		check=True, env=environment)
	built = Path(environment['CARGO_TARGET_DIR']) / 'release' / '_fsenum.dll'
	unexpected = imports(built) - EXPECTED_IMPORTS
	if unexpected:
		raise SystemExit('Unexpected DLL imports: %s' % ', '.join(sorted(unexpected)))
	print('Built %s (%d bytes); imports %s' % (built, built.stat().st_size, ', '.join(sorted(imports(built)))))
	if not args.no_record:
		shutil.copyfile(built, BINARY)
		source, binary = write_hashes()
		print('source %s\nbinary %s' % (source, binary))
	return 0


if __name__ == '__main__':
	sys.exit(main())
