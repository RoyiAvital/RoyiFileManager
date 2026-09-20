from contextlib import ExitStack
from datetime import datetime
from threading import Event

from fman import ApplicationCommand, DirectoryPaneCommand, QuicksearchItem, \
	Task, clear_status_message, load_json, save_json, show_quicksearch, \
	show_status_message, submit_task
from fman.impl.status_bar import format_size
from fman.url import as_human_readable

from search_file_fuzzy.indexer import build_index
from search_file_fuzzy.matcher import Matcher


_DEFAULT_SETTINGS = {
	'mode': 'fuzzy',
	'max_recursive_entries': 50_000,
	'max_results': 100,
	'include_hidden': True,
	'show_metadata': False,
}


class SearchFilesInCurrentFolder(DirectoryPaneCommand):
	aliases = ('Find files in current folder',)

	def __call__(self, mode=None, query='', metadata=None):
		_search(self.pane, recursive=False, mode=mode, query=query, metadata=metadata)


class SearchFilesRecursively(DirectoryPaneCommand):
	aliases = ('Find files recursively', 'Find files in subfolders')

	def __call__(self, mode=None, query='', metadata=None):
		_search(self.pane, recursive=True, mode=mode, query=query, metadata=metadata)


class ToggleSearchResultMetadata(ApplicationCommand):
	aliases = ('Toggle find result metadata', 'Find files: toggle modified date and size')

	def is_visible(self):
		return True

	def __call__(self):
		enabled = not _get_settings()['show_metadata']
		configured = load_json('SearchFileFuzzy.json', default={})
		values = dict(configured) if isinstance(configured, dict) else {}
		values['show_metadata'] = enabled
		try:
			save_json('SearchFileFuzzy.json', values)
		except ValueError as error:
			show_status_message('Find result metadata settings conflict: %s' % error, timeout_secs=5)
			return
		except OSError as error:
			show_status_message('Could not save find result metadata: %s' % error, timeout_secs=5)
			return
		show_status_message('Find result metadata: %s' % ('On' if enabled else 'Off'), timeout_secs=3)


class _IndexFiles(Task):
	def __init__(self, root_url, options, stale):
		super().__init__('Indexing files')
		self.root_url = root_url
		self.options = options
		self.stale = stale
		self.index = None

	def check_canceled(self):
		super().check_canceled()
		if self.stale.is_set():
			raise self.Canceled()

	def __call__(self):
		self.check_canceled()
		index = build_index(self.root_url, **self.options,
			collect_metadata=True, check_canceled=self.check_canceled)
		self.check_canceled()
		self.index = index


def _search(pane, recursive, mode=None, query='', metadata=None):
	settings = _get_settings(mode, metadata)
	with ExitStack() as subscriptions:
		stale = None
		if settings['show_metadata']:
			stale = Event()
			subscriptions.callback(pane.on_path_changed(stale.set))
			subscriptions.callback(pane.on_closed(stale.set))
		root_url = pane.get_path()
		options = dict(recursive=recursive, max_entries=settings['max_recursive_entries'],
			include_hidden=settings['include_hidden'])
		show_status_message('Indexing files...')
		index = None
		indexing_error = None
		try:
			if stale is None:
				index = build_index(root_url, **options)
			else:
				task = _IndexFiles(root_url, options, stale)
				submit_task(task)
				index = task.index
		except Task.Canceled:
			pass
		except OSError as error:
			indexing_error = error
		finally:
			clear_status_message()
		if stale is not None and (stale.is_set() or pane.get_path() != root_url):
			return
		if indexing_error is not None:
			show_status_message(
				'Could not index %s: %s' % (as_human_readable(root_url), indexing_error),
				timeout_secs=5
			)
			return
		if index is None:
			show_status_message('Find files canceled.', timeout_secs=3)
			return
		_show_results(pane, index, settings, query, stale)


def _show_results(pane, index, settings, query, stale):
	if not index.entries:
		show_status_message('No files found.', timeout_secs=3)
		return

	matcher = Matcher(
		index.entries, mode=settings['mode'],
		max_results=settings['max_results']
	)

	def get_items(current_query):
		if stale is not None and stale.is_set():
			return
		for entry, highlights in matcher.matches(current_query):
			yield QuicksearchItem(
				entry.url, title=entry.relative_path.replace('/', '\\'),
				highlight=highlights,
				description=(describe_metadata(entry) or ' ') if settings['show_metadata'] else ''
			)

	if stale is not None and stale.is_set():
		return
	result = show_quicksearch(get_items, query=query)
	if stale is not None and stale.is_set():
		return
	if index.truncated:
		show_status_message(
			'File list limited to the first %s entries.' %
			settings['max_recursive_entries'],
			timeout_secs=3
		)
	if result and result[1]:
		pane.run_command('open_directory', {'url': result[1]})


def describe_metadata(entry):
	parts = []
	if entry.modified_ns is not None:
		try:
			parts.append(datetime.fromtimestamp(entry.modified_ns / 1_000_000_000).strftime('%Y-%m-%d %H:%M'))
		except (OverflowError, OSError, ValueError):
			pass
	if entry.size_bytes is not None:
		parts.append(format_size(entry.size_bytes))
	return ', '.join(parts)


def _get_settings(mode=None, metadata=None):
	configured = load_json(
		'SearchFileFuzzy.json', default=_DEFAULT_SETTINGS.copy()
	)
	result = _DEFAULT_SETTINGS.copy()
	if isinstance(configured, dict):
		result.update(configured)
	if mode is not None:
		result['mode'] = mode
	if result['mode'] not in ('fuzzy', 'regular'):
		result['mode'] = _DEFAULT_SETTINGS['mode']
	result['max_recursive_entries'] = _positive_int(
		result['max_recursive_entries'],
		_DEFAULT_SETTINGS['max_recursive_entries']
	)
	result['max_results'] = _positive_int(
		result['max_results'], _DEFAULT_SETTINGS['max_results']
	)
	if not isinstance(result['include_hidden'], bool):
		result['include_hidden'] = _DEFAULT_SETTINGS['include_hidden']
	if metadata is not None:
		result['show_metadata'] = metadata
	if not isinstance(result['show_metadata'], bool):
		result['show_metadata'] = False
	return result


def _positive_int(value, default):
	try:
		value = int(value)
	except (TypeError, ValueError):
		return default
	return value if value > 0 else default