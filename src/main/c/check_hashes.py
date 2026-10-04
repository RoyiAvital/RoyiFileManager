"""Check that fsparser.c and _fsparser.pyd match fsparser.sha256.

    python src/main/c/check_hashes.py

Exit 0: both hashes match. Exit 1: a mismatch, with the reason. Exit 2: a file
is missing or unreadable.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fsparser_hashes import BINARY, SIDECAR, SOURCE, binary_hash, is_lfs_pointer, read_sidecar, source_hash  # noqa: E402


def check():
    """Return a list of problems; empty when the pairing holds."""
    for path in (SOURCE, BINARY, SIDECAR):
        if not path.is_file():
            return ['Missing %s' % path]
    try:
        expected_source, expected_binary = read_sidecar()
    except (ValueError, UnicodeDecodeError) as error:
        return ['Unreadable sidecar: %s' % error]
    problems = []
    actual_source = source_hash()
    if actual_source != expected_source:
        problems.append('fsparser.c changed since the binary was built (%s, recorded %s): '
            'rebuild _fsparser.pyd and run write_hashes.py' % (actual_source[:12], expected_source[:12]))
    if is_lfs_pointer(BINARY):
        problems.append('_fsparser.pyd is a Git LFS pointer, not the module: run `git lfs pull`')
    else:
        actual_binary = binary_hash()
        if actual_binary != expected_binary:
            problems.append('_fsparser.pyd does not match the recorded build (%s, recorded %s)'
                % (actual_binary[:12], expected_binary[:12]))
    return problems


def main():
    problems = check()
    if problems:
        for problem in problems:
            print(problem)
        return 2 if problems[0].startswith(('Missing', 'Unreadable')) else 1
    print('fsparser.c and _fsparser.pyd match fsparser.sha256')
    return 0


if __name__ == '__main__':
    sys.exit(main())
