from fman import DirectoryPaneCommand, QuicksearchItem, clear_status_message, \
	load_json, show_quicksearch, show_status_message
from fman.url import as_human_readable

from search_file_fuzzy.indexer import build_index
from search_file_fuzzy.matcher import Matcher


_DEFAULT_SETTINGS = {
	'mode': 'fuzzy',
	'max_recursive_entries': 50_000,
	'max_results': 100,
	'include_hidden': True,
}


class SearchFilesInCurrentFolder(DirectoryPaneCommand):
	aliases = ('Search files in current folder',)

	def __call__(self, mode=None, query=''):
		_search(self.pane, recursive=False, mode=mode, query=query)


class SearchFilesRecursively(DirectoryPaneCommand):
	aliases = ('Search files recursively', 'Search files in subfolders')

	def __call__(self, mode=None, query=''):
		_search(self.pane, recursive=True, mode=mode, query=query)


def _search(pane, recursive, mode=None, query=''):
	settings = _get_settings(mode)
	show_status_message('Indexing files...')
	try:
		root_url = pane.get_path()
		index = build_index(
			root_url, recursive=recursive,
			max_entries=settings['max_recursive_entries'],
			include_hidden=settings['include_hidden']
		)
	except OSError as error:
		indexing_error = error
	else:
		indexing_error = None
	finally:
		clear_status_message()
	if indexing_error is not None:
		show_status_message(
			'Could not index %s: %s' %
			(as_human_readable(root_url), indexing_error),
			timeout_secs=5
		)
		return
	if not index.entries:
		show_status_message('No files found.', timeout_secs=3)
		return

	matcher = Matcher(
		index.entries, mode=settings['mode'],
		max_results=settings['max_results']
	)

	def get_items(current_query):
		for entry, highlights in matcher.matches(current_query):
			yield QuicksearchItem(
				entry.url, title=entry.relative_path.replace('/', '\\'),
				highlight=highlights
			)

	result = show_quicksearch(get_items, query=query)
	if index.truncated:
		show_status_message(
			'Search limited to the first %s entries.' %
			settings['max_recursive_entries'],
			timeout_secs=3
		)
	if result and result[1]:
		pane.run_command('open_directory', {'url': result[1]})


def _get_settings(mode=None):
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
	return result


def _positive_int(value, default):
	try:
		value = int(value)
	except (TypeError, ValueError):
		return default
	return value if value > 0 else default