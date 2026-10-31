"""Attribute capture, merging and application. Uses the standard library only.

Attributes are read once and treated as static: chosen items when the command
starts, descendants when the walk lists their folder. Nothing is re-read before
writing; the user is responsible for concurrent changes by other programs.
"""

from dataclasses import dataclass
from typing import Callable, NamedTuple

import ctypes
import os
import stat


READONLY, HIDDEN, SYSTEM, ARCHIVE = 0x1, 0x2, 0x4, 0x20
TEMPORARY, NOT_INDEXED, NORMAL = 0x100, 0x2000, 0x80
# Bits SetFileAttributesW documents as settable: R, H, S, A, T, Offline,
# Not content indexed, No scrub data, Pinned, Unpinned. Others are never passed.
SETTABLE = READONLY | HIDDEN | SYSTEM | ARCHIVE | TEMPORARY | 0x1000 | NOT_INDEXED | \
	0x20000 | 0x80000 | 0x100000
# Reparse tags of links and junctions carry this bit.
NAME_SURROGATE = 0x20000000

ATTRIBUTES = (
	# ID, title, hint, flag, description
	('readonly', 'Read-only', 'R', READONLY, 'Prevent changes to file content; stored only on folders'),
	('hidden', 'Hidden', 'H', HIDDEN, 'Hide unless hidden files are shown'),
	('system', 'System', 'S', SYSTEM, 'Mark as an operating system file'),
	('archive', 'Archive', 'A', ARCHIVE, 'Changed since the last backup'),
	('not_indexed', 'Not content indexed', 'I', NOT_INDEXED, 'Exclude from Windows Search indexing'),
	('temporary', 'Temporary', 'T', TEMPORARY, 'Keep in memory when possible; files only'),
)
FLAGS = {attribute[0]: attribute[3] for attribute in ATTRIBUTES}
MAX_FAILURES = 1000
MAX_PATH_TEXT = 1024
MAX_ERROR_TEXT = 256


class Rejected(ValueError):
	pass


class Entry(NamedTuple):
	path: str
	attributes: int
	is_dir: bool


class StartState(NamedTuple):
	id: str
	title: str
	hint: str
	description: str
	state: str
	enabled: bool


def is_link(info):
	"""Whether an lstat-style result is a symbolic link, junction or other name surrogate."""
	return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_reparse_tag', 0) & NAME_SURROGATE)


def capture(paths, lstat=os.lstat, check=lambda: None):
	entries = []
	for path in paths:
		check()
		if path.startswith('\\\\'):
			raise Rejected('UNC paths are not supported: ' + path)
		try:
			info = lstat(path)
		except OSError as error:
			raise Rejected('%s: %s' % (path, error.strerror or error)) from None
		if is_link(info):
			raise Rejected('Select actual files and folders, not links or junctions: ' + path)
		entries.append(Entry(path, info.st_file_attributes, stat.S_ISDIR(info.st_mode)))
	return entries


def starting_states(entries):
	folders = any(entry.is_dir for entry in entries)
	result = []
	for attribute_id, title, hint, flag, description in ATTRIBUTES:
		temporary = attribute_id == 'temporary'
		pool = [entry for entry in entries if not entry.is_dir] if temporary else entries
		count = sum(bool(entry.attributes & flag) for entry in pool)
		state = 'off' if count == 0 else 'on' if count == len(pool) else 'mixed'
		result.append(StartState(attribute_id, title, hint, description, state, not (temporary and folders)))
	return result


def masks(changed):
	"""(add, remove) bit masks from QuickCheckList's changed states; mixed is never a change."""
	add = remove = 0
	for attribute_id, state in changed.items():
		if state == 'on':
			add |= FLAGS[attribute_id]
		elif state == 'off':
			remove |= FLAGS[attribute_id]
	return add, remove


_SetFileAttributesW = ctypes.WinDLL('kernel32', use_last_error=True).SetFileAttributesW
_SetFileAttributesW.argtypes = (ctypes.c_wchar_p, ctypes.c_uint32)
_SetFileAttributesW.restype = ctypes.c_int


def set_attributes(path, attributes):
	if not _SetFileAttributesW('\\\\?\\' + os.path.abspath(path), attributes):
		raise ctypes.WinError(ctypes.get_last_error())


def _ignore(*_):
	pass


@dataclass
class Operations:
	write: Callable = set_attributes
	scandir: Callable = os.scandir
	# Called with a folder path whose direct children changed.
	notify: Callable = _ignore
	check: Callable = _ignore
	progress: Callable = _ignore
	# Called after each chosen item, including its walk.
	step: Callable = _ignore


class Report:
	def __init__(self):
		self.changed = self.unchanged = self.skipped = self.failed = 0
		self.failures = []
		self.cancelled = False

	def fail(self, path, error):
		self.failed += 1
		if len(self.failures) < MAX_FAILURES:
			if len(path) > MAX_PATH_TEXT:
				half = (MAX_PATH_TEXT - 1) // 2
				path = path[:half] + '\u2026' + path[-half:]
			self.failures.append((path, str(error)[:MAX_ERROR_TEXT]))


def _update(path, attributes, add, remove, operations, report):
	current = attributes & SETTABLE
	target = (current & ~remove) | add
	if target == current:
		report.unchanged += 1
		return False
	try:
		operations.write(path, target or NORMAL)
	except OSError as error:
		report.fail(path, error)
		return False
	report.changed += 1
	return True


def _announce(operations, folder):
	try:
		operations.notify(folder)
	except Exception:
		# Writes are already counted; a failing observer never turns them into failures.
		pass


def apply(entries, add, remove, recursive, operations, report):
	"""Write add/remove to the chosen entries and, when recursive, to all descendants."""
	parents = set()
	try:
		for entry in entries:
			operations.check()
			operations.progress(entry.path)
			if _update(entry.path, entry.attributes, add, remove, operations, report):
				parents.add(os.path.dirname(entry.path))
			if recursive and entry.is_dir:
				_walk(entry.path, add, remove, operations, report)
			operations.step()
	finally:
		for folder in sorted(parents):
			_announce(operations, folder)


def _walk(root, add, remove, operations, report):
	# Frames: [folder, iterator, children changed]. Folders are announced when left.
	stack = []
	def enter(folder):
		try:
			stack.append([folder, operations.scandir(folder), False])
		except OSError as error:
			report.fail(folder, error)
	def leave(frame):
		close = getattr(frame[1], 'close', None)
		if close is not None:
			close()
		if frame[2]:
			_announce(operations, frame[0])
	enter(root)
	try:
		while stack:
			frame = stack[-1]
			try:
				child = next(frame[1], None)
			except OSError as error:
				report.fail(frame[0], error)
				child = None
			if child is None:
				leave(stack.pop())
				continue
			operations.check()
			try:
				info = child.stat(follow_symlinks=False)
			except OSError as error:
				report.fail(child.path, error)
				continue
			if is_link(info):
				report.skipped += 1
				continue
			operations.progress(child.path)
			if _update(child.path, info.st_file_attributes, add, remove, operations, report):
				frame[2] = True
			if stat.S_ISDIR(info.st_mode):
				enter(child.path)
	finally:
		while stack:
			leave(stack.pop())
