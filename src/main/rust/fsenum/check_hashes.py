"""Check that _fsenum.pyd matches its sources per fsenum.sha256.

    python src/main/rust/fsenum/check_hashes.py

Exit 0: the pairing holds. Exit 1: a mismatch, with the reason. Exit 2: a file
is missing or unreadable.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fsenum_hashes import check  # noqa: E402


def main():
	problems = check()
	if problems:
		for problem in problems:
			print(problem)
		return 2 if problems[0].startswith(('Missing', 'Unreadable')) else 1
	print('_fsenum.pyd matches its sources (fsenum.sha256)')
	return 0


if __name__ == '__main__':
	sys.exit(main())
