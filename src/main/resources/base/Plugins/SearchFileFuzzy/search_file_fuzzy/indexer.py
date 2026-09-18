from collections import deque, namedtuple
from stat import FILE_ATTRIBUTE_HIDDEN, FILE_ATTRIBUTE_REPARSE_POINT

from fman.fs import is_dir, iterdir, query
from fman.url import as_human_readable, join, splitscheme
from PyQt5.QtCore import QFileInfo

from search_file_fuzzy.matcher import SearchEntry

import os


IndexResult = namedtuple('IndexResult', 'entries truncated')


def build_index(
	root_url, recursive=False, max_entries=50_000, include_hidden=True,
	collect_metadata=False, check_canceled=None
):
	max_entries = max(1, int(max_entries))
	scheme, _ = splitscheme(root_url)
	if scheme == 'file://':
		return _build_local_index(
			root_url, recursive, max_entries, include_hidden,
			collect_metadata, check_canceled
		)
	return _build_fman_index(
		root_url, recursive, max_entries, include_hidden,
		collect_metadata, check_canceled
	)


def _build_local_index(
	root_url, recursive, max_entries, include_hidden, collect_metadata,
	check_canceled
):
	entries = []
	directories = deque([(as_human_readable(root_url), root_url, '')])
	inspected = 0

	while directories:
		if check_canceled is not None:
			check_canceled()
		local_directory, directory_url, relative_directory = \
			directories.popleft()
		try:
			with os.scandir(local_directory) as children:
				for child in children:
					if check_canceled is not None:
						check_canceled()
					if inspected == max_entries:
						return IndexResult(entries, True)
					inspected += 1
					stat_result = None
					try:
						if collect_metadata and not include_hidden and not child.name.startswith('.'):
							stat_result = child.stat(follow_symlinks=False)
						if not include_hidden and _is_local_hidden(child, stat_result):
							continue
						if _is_directory_link(child):
							continue
						is_directory = child.is_dir(follow_symlinks=False)
					except OSError:
						continue
					url = join(directory_url, child.name)
					relative_path = _join_relative(
						relative_directory, child.name
					)
					if is_directory:
						if recursive:
							directories.append(
								(child.path, url, relative_path)
							)
					else:
						metadata = _local_metadata(child, stat_result) if collect_metadata else ()
						if check_canceled is not None:
							check_canceled()
						entries.append(
							SearchEntry(url, child.name, relative_path, *metadata)
						)
		except OSError:
			if not relative_directory:
				raise
			continue

	return IndexResult(entries, False)


def _build_fman_index(
	root_url, recursive, max_entries, include_hidden, collect_metadata,
	check_canceled
):
	entries = []
	directories = deque([(root_url, '')])
	inspected = 0

	while directories:
		if check_canceled is not None:
			check_canceled()
		directory_url, relative_directory = directories.popleft()
		try:
			names = list(iterdir(directory_url))
		except OSError:
			continue
		for name in names:
			if check_canceled is not None:
				check_canceled()
			if inspected == max_entries:
				return IndexResult(entries, True)
			inspected += 1
			url = join(directory_url, name)
			if not include_hidden and _is_hidden(url, name):
				continue
			relative_path = _join_relative(relative_directory, name)
			try:
				url_is_directory = is_dir(url)
			except OSError:
				continue
			if url_is_directory:
				if recursive:
					directories.append((url, relative_path))
			else:
				metadata = _provider_metadata(url, check_canceled) if collect_metadata else ()
				entries.append(SearchEntry(url, name, relative_path, *metadata))

	return IndexResult(entries, False)


def _local_metadata(entry, stat_result):
	try:
		if stat_result is None:
			stat_result = entry.stat(follow_symlinks=False)
		if entry.is_symlink() or getattr(stat_result, 'st_file_attributes', 0) & FILE_ATTRIBUTE_REPARSE_POINT:
			try:
				stat_result = entry.stat()
			except FileNotFoundError:
				pass
		return stat_result.st_size, stat_result.st_mtime_ns
	except OSError:
		return None, None


def _provider_metadata(url, check_canceled):
	values = []
	for attribute in ('size_bytes', 'modified_datetime'):
		if check_canceled is not None:
			check_canceled()
		try:
			value = query(url, attribute)
			if attribute == 'modified_datetime':
				value = int(value.timestamp() * 1_000_000_000) if value is not None else None
			elif not isinstance(value, int) or isinstance(value, bool) or value < 0:
				value = None
		except (OSError, NotImplementedError, AttributeError, TypeError, ValueError, OverflowError):
			value = None
		values.append(value)
	if check_canceled is not None:
		check_canceled()
	return values


def _is_local_hidden(entry, stat_result=None):
	if entry.name.startswith('.'):
		return True
	if stat_result is None:
		stat_result = entry.stat(follow_symlinks=False)
	attributes = getattr(
		stat_result, 'st_file_attributes', 0
	)
	return bool(attributes & FILE_ATTRIBUTE_HIDDEN)


def _is_directory_link(entry):
	if getattr(entry, 'is_junction', lambda: False)():
		return True
	return entry.is_symlink() and entry.is_dir()


def _join_relative(directory, name):
	if directory:
		return directory + '/' + name
	return name


def _is_hidden(url, name):
	if name.startswith('.'):
		return True
	scheme, _ = splitscheme(url)
	return scheme == 'file://' and QFileInfo(as_human_readable(url)).isHidden()