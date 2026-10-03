"""Validate native build inputs and optionally package ChecksumFiles offline."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import sys


PINNED_FILES = {
    'blake3.cp314-win_amd64.pyd': '8996731bff9786e211205fd59ebac33d2fc2fabe15f1215779b2cd2ba1e1fd9a',
    '__init__.py': '8b919729adf98380edfe138af0e98214663eeb10edce64c01a57a9485bffd27b',
    '__init__.pyi': 'c6a209ff734485754ee80aa6c877b59d978797d942ce101a9b4264ba8eee7d85',
    'py.typed': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
}


def native_files():
    distribution = importlib.metadata.distribution('blake3')
    if distribution.version != '1.0.10' or sys.version_info[:2] != (3, 14) or sys.platform != 'win32' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise ValueError('This package requires the pinned BLAKE3 1.0.10 / CPython 3.14 Windows x64 artifact.')
    source = Path(distribution.locate_file('blake3'))
    for name, expected in PINNED_FILES.items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Installed BLAKE3 does not match the pinned artifact: ' + name)
    license_path = Path(distribution.locate_file('blake3-1.0.10.dist-info/licenses/LICENSE'))
    if not license_path.is_file():
        raise ValueError('BLAKE3 redistribution license is missing.')
    return tuple(source / name for name in PINNED_FILES) + (license_path,)


def package(destination):
    native = native_files()
    destination = Path(destination).absolute()
    destination.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parent
    try:
        shutil.copytree(root / 'checksum_files', destination / 'checksum_files', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '_vendor'))
        for name in ('ChecksumFiles.json', 'README.md'):
            shutil.copy2(root / name, destination / name)
        vendor = destination / 'checksum_files' / '_vendor' / 'blake3'
        vendor.mkdir(parents=True)
        for path in native:
            shutil.copy2(path, vendor / path.name)
        metadata = {
            'plugin': 'ChecksumFiles', 'host_api_tested': '0.10.2',
            'python_abi': 'cp314', 'platform': 'win_amd64',
            'blake3_version': '1.0.10',
            'origin': 'Installed blake3 distribution; package bytes pinned to the verified 1.0.10 cp314 Windows x64 installation.',
            'host_dependencies': ['python314.dll', 'VCRUNTIME140.dll', 'Windows system DLLs and Universal CRT'],
            'files': {str(path.relative_to(destination)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in sorted(destination.rglob('*')) if path.is_file()},
        }
        (destination / 'package-manifest.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    except BaseException:
        shutil.rmtree(destination)
        raise
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New destination directory; existing directories are refused.')
    arguments = parser.parse_args()
    print(package(arguments.output))


if __name__ == '__main__':
    main()