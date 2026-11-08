"""Explorer items offered without file paths, such as entries inside a ZIP folder.

Explorer's archive view puts no file list (CF_HDROP) on the clipboard or in a
drag. It offers a "Shell IDList Array" instead. The shell, not the item's name,
says where each archive ends: walking up from an item, the first ancestor that
is a real file is the archive; the names below it are the archive members.
Members map to the archive file system with `archive_handlers` (AppSettings.yaml):

	C:\\Data\\Reports.zip\\folder  ->  zip://C:/Data/Reports.zip/folder

A selection is used whole or not at all: one unreadable or unsupported item
gives a problem message and no URLs, so items are never silently left out.
"""
from collections import namedtuple
from fman.impl.util.qt import from_qurl
from fman.impl.util.qt.thread import run_in_main_thread
from fman.url import as_url, splitscheme

import ntpath

SHELL_IDLIST_MIME = 'application/x-qt-windows-mime;value="Shell IDList Array"'

ShellSelection = namedtuple('ShellSelection', 'urls problem')

_cache = (None, None)


def dropped_urls(mime):
	"""Return (urls, from_shell). Shell selections with a problem give no URLs."""
	urls = []
	for qurl in mime.urls():
		try:
			urls.append(from_qurl(qurl))
		except ValueError:
			# For instance QUrl(''), or plain text on the text/uri-list clipboard.
			pass
	if urls:
		return urls, False
	selection = shell_selection(mime)
	if selection is None:
		return [], False
	return list(selection.urls), True


def forget_failure():
	"""Retry a failed lookup on the next request. Call when a paste or drag starts;
	drag-move events in between reuse the cached result."""
	global _cache
	if _cache[1] is not None and _cache[1][1]:
		_cache = (None, None)


@run_in_main_thread
def clipboard_problem():
	"""Why the clipboard's Explorer items cannot be pasted, or None."""
	from fman.clipboard import _clipboard
	selection = shell_selection(_clipboard().mimeData())
	return None if selection is None else selection.problem


def shell_selection(mime):
	"""The shell items in `mime` as a ShellSelection, or None without shell items.

	Call on the Qt thread: it uses the thread's COM apartment.
	"""
	global _cache
	if not mime.hasFormat(SHELL_IDLIST_MIME):
		return None
	raw = bytes(mime.data(SHELL_IDLIST_MIME))
	if raw != _cache[0]:
		# Drag-move events repeat the same data; resolve it with the shell once.
		_cache = raw, _locate_all(raw)
	locations, problem = _cache[1]
	if problem:
		return ShellSelection((), problem)
	return _to_urls(locations)


def _locate_all(raw):
	"""((file system path, member names), ...) and a problem message or None."""
	from win32com.shell import shell
	try:
		parent, children = shell.StringAsCIDA(raw)
	except Exception as error:
		return (), 'The items offered by Explorer could not be read (%s).' % _describe(error)
	locations = []
	for child in children:
		try:
			item = shell.SHCreateItemFromIDList(parent + child, shell.IID_IShellItem)
		except Exception as error:
			return (), 'An item offered by Explorer could not be read (%s).' % _describe(error)
		location = _locate(item)
		if isinstance(location, str):
			return (), location
		locations.append(location)
	return tuple(locations), None


def _locate(item):
	"""(path, members) for a file system item or an archive member; a problem message otherwise."""
	from win32com.shell import shellcon
	try:
		name = item.GetDisplayName(shellcon.SIGDN_NORMALDISPLAY)
	except Exception:
		name = 'An item'
	members = []
	try:
		while True:
			attributes = item.GetAttributes(shellcon.SFGAO_FILESYSTEM | shellcon.SFGAO_STREAM)
			if attributes & shellcon.SFGAO_FILESYSTEM:
				# A member's file system ancestor must be a file (the archive), not a folder.
				if members and not attributes & shellcon.SFGAO_STREAM:
					break
				return item.GetDisplayName(shellcon.SIGDN_FILESYSPATH), tuple(reversed(members))
			members.append(item.GetDisplayName(shellcon.SIGDN_PARENTRELATIVEPARSING))
			item = item.GetParent()
	except Exception:
		# GetParent fails above the shell root: the item is not on disk.
		pass
	return '%s is not a file, folder or archive entry on disk.' % name


def _to_urls(locations):
	handlers = None
	urls = []
	for path, members in locations:
		if not members:
			urls.append(as_url(path))
			continue
		if handlers is None:
			handlers = _archive_handlers()
		scheme = archive_scheme(ntpath.basename(path), handlers)
		if scheme is None:
			return ShellSelection((), '%s: this archive type has no entry in archive_handlers '
				'(AppSettings.yaml).' % ntpath.basename(path))
		urls.append(scheme + splitscheme(as_url(path))[1] + '/' + '/'.join(members))
	return ShellSelection(tuple(urls), None)


def archive_scheme(file_name, handlers):
	"""The scheme for the longest matching archive suffix, e.g. 'zip://', or None."""
	name = file_name.lower()
	for suffix, scheme in sorted(handlers.items(), key=lambda pair: -len(pair[0])):
		if name.endswith(suffix):
			return scheme
	return None


def _archive_handlers():
	# Never creates the application context: tests and tools may have none.
	from fman.impl.application_context import get_existing_application_context
	context = get_existing_application_context()
	settings = {} if context is None else context.config.load_json('AppSettings.yaml', {})
	handlers = settings.get('archive_handlers', {}) if isinstance(settings, dict) else {}
	return handlers if isinstance(handlers, dict) else {}


def _describe(error):
	return getattr(error, 'strerror', None) or str(error) or type(error).__name__
