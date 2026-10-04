"""Write fsparser.sha256 for the current fsparser.c and _fsparser.pyd.

    python src/main/c/write_hashes.py [--from target/native/_fsparser.pyd]

`--from` copies a freshly built module into place first. Exit 2 when a file is
missing or the binary is a Git LFS pointer rather than the module itself.
"""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fsparser_hashes import BINARY, SIDECAR, SOURCE, binary_hash, is_lfs_pointer, source_hash, write_sidecar  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--from', dest='built', help='copy this built .pyd to %s first' % BINARY.name)
    args = parser.parse_args(argv)
    if args.built:
        built = Path(args.built)
        if not built.is_file():
            parser.exit(2, 'Not a file: %s\n' % built)
        shutil.copyfile(built, BINARY)
    for path in (SOURCE, BINARY):
        if not path.is_file():
            parser.exit(2, 'Missing %s\n' % path)
    if is_lfs_pointer(BINARY):
        parser.exit(2, '%s is a Git LFS pointer; run `git lfs pull` or pass --from\n' % BINARY)
    source, binary = source_hash(), binary_hash()
    write_sidecar(source, binary)
    print('source %s' % source)
    print('binary %s' % binary)
    print('Wrote %s' % SIDECAR)
    return 0


if __name__ == '__main__':
    sys.exit(main())
