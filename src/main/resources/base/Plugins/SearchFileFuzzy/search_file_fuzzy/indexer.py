from collections import deque, namedtuple
from stat import FILE_ATTRIBUTE_HIDDEN

from fman.fs import is_dir, iterdir
from fman.url import as_human_readable, join, splitscheme
from PyQt5.QtCore import QFileInfo

from search_file_fuzzy.matcher import SearchEntry

import os


IndexResult = namedtuple('IndexResult', 'entries truncated')


def build_index(
	root_url, recursive=False, max_entries=50_000, include_hidden=True
):
	max_entries = max(1, int(max_entries))
	scheme, _ = splitscheme(root_url)
	if scheme == 'file://':
		return _build_local_index(
			root_url, recursive, max_entries, include_hidden
		)
	return _build_fman_index(
		root_url, recursive, max_entries, include_hidden
	)


def _build_local_index(root_url, recursive, max_entries, include_hidden):
	entries = []
	directories = deque([(as_human_readable(root_url), root_url, '')])
	inspected = 0

	while directories:
		local_directory, directory_url, relative_directory = \
			directories.popleft()
		try:
			with os.scandir(local_directory) as children:
				for child in children:
					if inspected == max_entries:
						return IndexResult(entries, True)
					inspected += 1
					try:
						if not include_hidden and _is_local_hidden(child):
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
						entries.append(
							SearchEntry(url, child.name, relative_path)
						)
		except OSError:
			if not relative_directory:
				raise
			continue

	return IndexResult(entries, False)


def _build_fman_index(root_url, recursive, max_entries, include_hidden):
	entries = []
	directories = deque([(root_url, '')])
	inspected = 0

	while directories:
		directory_url, relative_directory = directories.popleft()
		try:
			names = list(iterdir(directory_url))
		except OSError:
			continue
		for name in names:
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
				entries.append(SearchEntry(url, name, relative_path))

	return IndexResult(entries, False)


def _is_local_hidden(entry):
	if entry.name.startswith('.'):
		return True
	attributes = getattr(
		entry.stat(follow_symlinks=False), 'st_file_attributes', 0
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