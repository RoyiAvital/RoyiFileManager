"""Gauge and parity check for the native directory enumerator `_fsenum`
(Plan/DirectoryEnumerator001.md).

For each folder, compares the application's scan() from
core/fs/local/windows/listing.py with a pure-Python reference: the folder's
kernel batches read with ctypes, records() per batch, os.stat for links, a
validated Listing, and sorted() over natural_key for the Name order. Then
reports medians of:

* kernel  -- the kernel enumeration alone (ctypes, the calls _fsenum makes)
* scan    -- scan(): columns, scope and the sorted Name order
* rescan  -- scan(previous) of the unchanged folder, which returns `previous`
* order   -- the descending Name order and the hidden-file filter on it
* python  -- the reference above

    python src/misc/benchmark_fsenum.py <folder> [<folder> ...] [--repeat 7]

Exit code 0: parity holds. Exit code 1: a mismatch. Exit code 2: a folder
outside the native scope (UNC, FAT, ...). Read-only. Run it, with
core.tests.fs.test_fsenum, after every change to src/main/rust/fsenum.

The kernel time of a folder depends on whether its files were used lately
(see BUFFER_BYTES in src/main/rust/fsenum/src/pipeline.rs): compare builds on
the same folder in the same state, alternating.
"""

import argparse
import ctypes
import os
import statistics
import sys
import time
from array import array
from ctypes import wintypes
from pathlib import Path
from stat import S_ISDIR, FILE_ATTRIBUTE_DIRECTORY, FILE_ATTRIBUTE_HIDDEN, FILE_ATTRIBUTE_REPARSE_POINT

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src' / 'main' / 'python'),
	str(ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' / 'Core')]

from core.fs.local.windows import listing as scanner  # noqa: E402
from fman.impl.util.natural import natural_key  # noqa: E402
from fman.listing import Listing  # noqa: E402

BUFFER_SIZE = 60 << 10  # as BUFFER_BYTES in src/main/rust/fsenum/src/pipeline.rs
KERNEL32 = ctypes.WinDLL('kernel32', use_last_error=True)
KERNEL32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
	wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
KERNEL32.CreateFileW.restype = wintypes.HANDLE
KERNEL32.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]


def kernel_calls(path):
	"""The folder's FILE_ID_EXTD_DIR_INFO batches, one per kernel call, in one
	buffer that is zero-filled before each call: use a batch before the next."""
	handle = KERNEL32.CreateFileW('\\\\?\\' + os.path.abspath(path), 0x81, 7, None, 3, 0x02000000, None)
	if handle == ctypes.c_void_p(-1).value:
		raise ctypes.WinError(ctypes.get_last_error())
	try:
		buffer = ctypes.create_string_buffer(BUFFER_SIZE)
		information_class = 20
		while True:
			ctypes.memset(buffer, 0, BUFFER_SIZE)
			if not KERNEL32.GetFileInformationByHandleEx(handle, information_class, buffer, BUFFER_SIZE):
				error = ctypes.get_last_error()
				if error == 18:
					return
				raise ctypes.WinError(error)
			yield buffer
			information_class = 19
	finally:
		KERNEL32.CloseHandle(handle)


def python_scan(location, path, scope):
	"""Reference: records() per batch, os.stat for links, a validated Listing."""
	names, directories, sizes, mtimes, attributes, created = ([] for _ in range(6))
	identities = bytearray()
	for batch in kernel_calls(path):
		for name, size, modified, own_attributes, tag, identity, birth in scanner.records(batch.raw):
			is_dir = bool(own_attributes & FILE_ATTRIBUTE_DIRECTORY)
			if own_attributes & FILE_ATTRIBUTE_REPARSE_POINT and tag in scanner._LINK_TAGS:
				try:
					metadata = os.stat(os.path.join(path, name))
				except OSError:
					pass
				else:
					is_dir, size, modified = S_ISDIR(metadata.st_mode), metadata.st_size, metadata.st_mtime_ns
			names.append(name)
			directories.append(is_dir)
			sizes.append(size)
			mtimes.append(modified)
			attributes.append(own_attributes)
			created.append(birth)
			identities.extend(identity)
	return Listing(location, names, directories, sizes, mtimes, attributes, created, bytes(identities), scope)


def python_order(listing, ascending):
	"""Core's Name sort: stable sorted() over ('1' or '0') + natural_key(name)."""
	keys = tuple(('1' if is_dir ^ ascending else '0') + natural_key(name)
		for name, is_dir in zip(listing.names, listing.is_dir))
	return sorted(range(len(keys)), key=keys.__getitem__, reverse=not ascending)


def timed(function, repeat):
	"""Median and minimum milliseconds; each result is freed outside the timing."""
	values = []
	for _ in range(repeat):
		started = time.perf_counter()
		result = function()
		values.append((time.perf_counter() - started) * 1000)
		del result
	return statistics.median(values), min(values)


def mismatches(native, reference, path):
	problems = []
	if native != reference or native.identities != reference.identities:
		fields = [field for field in ('names', 'is_dir', 'sizes', 'mtimes_ns', 'attributes', 'created_ns',
			'identities', 'scope') if getattr(native, field) != getattr(reference, field)]
		problems.append('columns differ: ' + ', '.join(fields))
	if os.stat(path).st_ino != int.from_bytes(native.scope[1], 'little'):
		problems.append('scope differs from os.stat')
	table = native._native
	for ascending in (True, False):
		order = array('I', scanner._fsenum.order(table, ascending))
		expected = python_order(reference, ascending)
		if list(order) != expected:
			problems.append('Name order differs (ascending=%s)' % ascending)
		shown = array('I', scanner._fsenum.without_attributes(table, order, FILE_ATTRIBUTE_HIDDEN))
		if list(shown) != [index for index in expected if not reference.attributes[index] & FILE_ATTRIBUTE_HIDDEN]:
			problems.append('hidden-file filter differs (ascending=%s)' % ascending)
	return problems


def main(argv=None):
	parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
	parser.add_argument('folders', nargs='+')
	parser.add_argument('--repeat', type=int, default=7)
	args = parser.parse_args(argv)
	status = 0
	for folder in args.folders:
		path = os.path.abspath(folder)
		location = 'file://' + path.replace('\\', '/')
		native = scanner.scan(location, path, lambda: None)
		if native is None:
			print('%s: outside the native scope (UNC or not NTFS/ReFS)' % path)
			status = max(status, 2)
			continue
		problems = mismatches(native, python_scan(location, path, native.scope), path)
		print('%s: %d entries, %s' % (path, len(native.names), '; '.join(problems) or 'parity holds'))
		if problems:
			status = 1
		table = native._native
		results = (
			('kernel', timed(lambda: sum(1 for _ in kernel_calls(path)), args.repeat)),
			('scan', timed(lambda: scanner.scan(location, path, lambda: None), args.repeat)),
			('rescan', timed(lambda: scanner.scan(location, path, lambda: None, native), args.repeat)),
			('order', timed(lambda: scanner._fsenum.without_attributes(
				table, array('I', scanner._fsenum.order(table, False)), FILE_ATTRIBUTE_HIDDEN), args.repeat)),
			('python', timed(lambda: (python_order(python_scan(location, path, native.scope), True)),
				max(1, args.repeat // 3))),
		)
		for label, (median, minimum) in results:
			print('  %-7s median %8.2f ms   min %8.2f ms' % (label, median, minimum))
	return status


if __name__ == '__main__':
	sys.exit(main())
