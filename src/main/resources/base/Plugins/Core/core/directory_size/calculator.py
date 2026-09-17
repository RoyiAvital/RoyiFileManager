from dataclasses import dataclass
from stat import S_ISDIR, S_ISLNK
from time import monotonic

import os


@dataclass(frozen=True)
class DirSize:
	size_bytes: int | None = 0
	files: int = 0
	entries: int = 0
	complete: bool = False
	capped: bool = False
	errors: bool = False
	skipped_link: bool = False


def walk_directory(path, max_files, check, clock=monotonic):
	check()
	try:
		info = os.lstat(path)
		if S_ISLNK(info.st_mode) or os.path.isjunction(path):
			yield DirSize(None, complete=True, skipped_link=True)
			return
		if not S_ISDIR(info.st_mode):
			raise NotADirectoryError(path)
	except OSError:
		yield DirSize(None, complete=True, errors=True)
		return
	size_bytes = files = entries = 0
	errors = False
	pending = [os.fspath(path)]
	last_progress = clock()
	while pending:
		check()
		directory = pending.pop()
		try:
			with os.scandir(directory) as children:
				for entry in children:
					if entries % 256 == 0:
						check()
					entries += 1
					try:
						if entry.is_symlink() or entry.is_junction():
							continue
						if entry.is_dir(follow_symlinks=False):
							pending.append(entry.path)
						elif entry.is_file(follow_symlinks=False):
							if max_files and files >= max_files:
								yield DirSize(size_bytes, files, entries, True, True, errors)
								return
							size_bytes += entry.stat(follow_symlinks=False).st_size
							files += 1
					except OSError:
						errors = True
					if clock() - last_progress >= .2:
						check()
						yield DirSize(size_bytes, files, entries, errors=errors)
						last_progress = clock()
		except InterruptedError:
			raise
		except OSError:
			if directory == os.fspath(path):
				yield DirSize(None, complete=True, errors=True)
				return
			errors = True
	check()
	yield DirSize(size_bytes, files, entries, True, errors=errors)


def scan_parents(parents, max_files, check, publish, clock=monotonic):
	changed = {}
	last_publish = clock() - .2
	for parent in parents:
		check()
		try:
			with os.scandir(parent) as children:
				for entry in children:
					check()
					try:
						is_directory = entry.is_dir(follow_symlinks=False) or entry.is_symlink()
					except OSError:
						changed[entry.path] = DirSize(None, complete=True, errors=True)
					else:
						if not is_directory:
							continue
						for result in walk_directory(entry.path, max_files, check, clock):
							changed[entry.path] = result
							if clock() - last_publish >= .2:
								check()
								publish(dict(changed))
								changed.clear()
								last_publish = clock()
		except InterruptedError:
			raise
		except OSError:
			changed[parent] = DirSize(None, complete=True, errors=True)
	check()
	if changed:
		publish(changed)