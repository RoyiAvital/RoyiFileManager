from pathlib import Path
from stat import FILE_ATTRIBUTE_HIDDEN
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch

from search_file_fuzzy import SearchFilesInCurrentFolder, _get_settings
from search_file_fuzzy.indexer import IndexResult, _is_directory_link, build_index
from search_file_fuzzy.matcher import Matcher, SearchEntry, normalize
from fman.url import as_url

import os


class NormalizeTest(TestCase):
	def test_normalizes_camel_case_and_separators(self):
		self.assertEqual(
			'security health host exe', normalize('SecurityHealthHost.exe')
		)

	def test_preserves_french_and_spanish_letters(self):
		self.assertEqual(
			'résumé annuel año pdf', normalize('Résumé_Annuel-Año.pdf')
		)

	def test_splits_unicode_camel_case(self):
		self.assertEqual(
			'résumé annuel año fiscal', normalize('RésuméAnnuel_AñoFiscal')
		)


class MatcherTest(TestCase):
	def setUp(self):
		self.entries = [
			SearchEntry('file:///root/docs/report.txt', 'report.txt', 'docs/report.txt'),
			SearchEntry(
				'file:///root/SecurityHealthHost.exe',
				'SecurityHealthHost.exe', 'SecurityHealthHost.exe'
			),
			SearchEntry('file:///root/helper.py', 'helper.py', 'helper.py'),
		]

	def test_regular_search_is_normalized_substring_search(self):
		matcher = Matcher(self.entries, mode='regular')
		self.assertEqual(
			[self.entries[1]], matcher('security health')
		)

	def test_fuzzy_search_matches_subsequences(self):
		matcher = Matcher(self.entries, mode='fuzzy')
		self.assertEqual(self.entries[1], matcher('scrty hlth')[0])

	def test_fuzzy_search_matches_unicode_filename(self):
		entry = SearchEntry(
			'file:///root/Résumé_Annuel.pdf', 'Résumé_Annuel.pdf',
			'Résumé_Annuel.pdf'
		)
		self.assertEqual(entry, Matcher([entry])('résmé anel')[0])

	def test_filename_match_ranks_before_path_match(self):
		path_match = SearchEntry(
			'file:///root/report/archive.txt', 'archive.txt',
			'report/archive.txt'
		)
		matcher = Matcher([path_match, self.entries[0]], mode='fuzzy')
		self.assertEqual(self.entries[0], matcher('report')[0])

	def test_result_count_is_bounded(self):
		for mode in ('fuzzy', 'regular'):
			with self.subTest(mode=mode):
				matcher = Matcher(self.entries, mode=mode, max_results=2)
				self.assertEqual(2, len(matcher('e')))

	def test_rejects_unknown_mode(self):
		with self.assertRaises(ValueError):
			Matcher(self.entries, mode='typo')


class BuildIndexTest(TestCase):
	def test_traverses_local_directories_breadth_first(self):
		with TemporaryDirectory() as root:
			root_path = Path(root)
			(root_path / 'a').mkdir()
			(root_path / 'a' / 'c').mkdir()
			(root_path / 'b').mkdir()
			(root_path / 'root.txt').touch()
			(root_path / 'a' / 'a.txt').touch()
			(root_path / 'a' / 'c' / 'deep.txt').touch()
			(root_path / 'b' / 'b.txt').touch()

			result = build_index(as_url(root), recursive=True)

		paths = [entry.relative_path for entry in result.entries]
		self.assertEqual('root.txt', paths[0])
		self.assertEqual(
			{'root.txt', 'a/a.txt', 'b/b.txt', 'a/c/deep.txt'}, set(paths)
		)
		self.assertLess(paths.index('a/a.txt'), paths.index('a/c/deep.txt'))
		self.assertLess(paths.index('b/b.txt'), paths.index('a/c/deep.txt'))
		self.assertFalse(result.truncated)

	def test_inaccessible_root_error_is_not_swallowed(self):
		with TemporaryDirectory() as root:
			with patch(
				'search_file_fuzzy.indexer.os.scandir',
				side_effect=PermissionError('denied')
			):
				with self.assertRaises(PermissionError):
					build_index(as_url(root), recursive=True)

	def test_inaccessible_descendant_is_skipped_but_other_results_remain(self):
		with TemporaryDirectory() as root:
			root_path = Path(root)
			blocked = root_path / 'blocked'
			blocked.mkdir()
			(blocked / 'blocked.txt').touch()
			allowed = root_path / 'allowed'
			allowed.mkdir()
			(allowed / 'allowed.txt').touch()
			real_scandir = os.scandir

			def scandir(path):
				if os.path.normcase(os.fspath(path)) == \
						os.path.normcase(str(blocked)):
					raise PermissionError('denied')
				return real_scandir(path)

			with patch(
				'search_file_fuzzy.indexer.os.scandir', side_effect=scandir
			):
				result = build_index(as_url(root), recursive=True)

		self.assertEqual(
			['allowed/allowed.txt'],
			[entry.relative_path for entry in result.entries]
		)
		self.assertFalse(result.truncated)

	def test_partial_descendant_results_survive_iteration_error(self):
		with TemporaryDirectory() as root:
			root_path = Path(root)
			partial = root_path / 'partial'
			partial.mkdir()
			(partial / 'first.txt').touch()
			(partial / 'second.txt').touch()
			(root_path / 'root.txt').touch()
			real_scandir = os.scandir

			class FailingIterator:
				def __init__(self, path):
					self._iterator = real_scandir(path)
					self._yielded = False

				def __enter__(self):
					return self

				def __exit__(self, *args):
					self._iterator.close()

				def __iter__(self):
					return self

				def __next__(self):
					if self._yielded:
						raise PermissionError('denied during iteration')
					self._yielded = True
					return next(self._iterator)

			def scandir(path):
				if os.path.normcase(os.fspath(path)) == \
						os.path.normcase(str(partial)):
					return FailingIterator(path)
				return real_scandir(path)

			with patch(
				'search_file_fuzzy.indexer.os.scandir', side_effect=scandir
			):
				result = build_index(as_url(root), recursive=True)

		paths = [entry.relative_path for entry in result.entries]
		self.assertIn('root.txt', paths)
		self.assertEqual(1, len([path for path in paths if path.startswith('partial/')]))
		self.assertFalse(result.truncated)

	def test_second_local_index_sees_new_file(self):
		with TemporaryDirectory() as root:
			root_url = as_url(root)
			self.assertEqual([], build_index(root_url).entries)
			(Path(root) / 'nouveau.txt').touch()

			result = build_index(root_url)

		self.assertEqual(['nouveau.txt'], [entry.name for entry in result.entries])

	def test_stops_at_entry_limit(self):
		with TemporaryDirectory() as root:
			for name in ('a', 'b', 'c'):
				(Path(root) / name).touch()
			result = build_index(as_url(root), max_entries=2)

		self.assertEqual(2, len(result.entries))
		self.assertTrue(result.truncated)

	def test_can_exclude_dot_prefixed_entries(self):
		with TemporaryDirectory() as root:
			(Path(root) / '.hidden').touch()
			(Path(root) / 'visible').touch()
			result = build_index(as_url(root), include_hidden=False)

		self.assertEqual(['visible'], [entry.name for entry in result.entries])

	def test_excluding_hidden_entries_prunes_hidden_directories(self):
		with TemporaryDirectory() as root:
			root_path = Path(root)
			(root_path / '.hidden').mkdir()
			(root_path / '.hidden' / 'nested.txt').touch()
			(root_path / 'visible.txt').touch()

			result = build_index(
				as_url(root), recursive=True, include_hidden=False
			)

		self.assertEqual(
			['visible.txt'], [entry.relative_path for entry in result.entries]
		)

	@skipUnless(os.name == 'nt', 'Windows file attributes are unavailable')
	def test_can_exclude_windows_hidden_file(self):
		import ctypes

		get_attributes = ctypes.windll.kernel32.GetFileAttributesW
		get_attributes.argtypes = [ctypes.c_wchar_p]
		get_attributes.restype = ctypes.c_uint32
		set_attributes = ctypes.windll.kernel32.SetFileAttributesW
		set_attributes.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
		set_attributes.restype = ctypes.c_bool
		with TemporaryDirectory() as root:
			hidden = Path(root) / 'hidden.txt'
			hidden.touch()
			attributes = get_attributes(str(hidden))
			self.assertTrue(
				set_attributes(str(hidden), attributes | FILE_ATTRIBUTE_HIDDEN)
			)
			try:
				result = build_index(as_url(root), include_hidden=False)
			finally:
				set_attributes(str(hidden), attributes)

		self.assertEqual([], result.entries)

	@skipUnless(hasattr(os, 'symlink'), 'symbolic links are unavailable')
	def test_does_not_follow_directory_symlink(self):
		with TemporaryDirectory() as root:
			root_path = Path(root)
			(root_path / 'target').mkdir()
			(root_path / 'target' / 'nested.txt').touch()
			try:
				os.symlink(
					root_path, root_path / 'target' / 'loop',
					target_is_directory=True
				)
			except OSError as error:
				self.skipTest('Creating directory symlinks is unavailable: %s' % error)

			result = build_index(as_url(root), recursive=True, max_entries=20)

		self.assertEqual(
			['target/nested.txt'],
			[entry.relative_path for entry in result.entries]
		)
		self.assertFalse(result.truncated)

	@skipUnless(os.name == 'nt', 'Windows junctions are unavailable')
	def test_does_not_follow_junction_cycle(self):
		import _winapi

		with TemporaryDirectory() as root:
			root_path = Path(root)
			target = root_path / 'target'
			target.mkdir()
			(target / 'nested.txt').touch()
			junction = target / 'loop'
			_winapi.CreateJunction(str(root_path), str(junction))
			try:
				result = build_index(
					as_url(root), recursive=True, max_entries=20
				)
			finally:
				os.rmdir(junction)

		self.assertEqual(
			['target/nested.txt'],
			[entry.relative_path for entry in result.entries]
		)
		self.assertFalse(result.truncated)

	@patch('search_file_fuzzy.indexer.is_dir', return_value=False)
	@patch('search_file_fuzzy.indexer.iterdir', return_value=['remote.txt'])
	def test_non_local_scheme_uses_fman_filesystem(self, iterdir, is_dir):
		result = build_index('example://root')

		self.assertEqual(['remote.txt'], [entry.name for entry in result.entries])

	def test_detects_junction(self):
		entry = Mock()
		entry.is_junction.return_value = True

		self.assertTrue(_is_directory_link(entry))

	def test_detects_directory_symlink(self):
		entry = Mock()
		entry.is_junction.return_value = False
		entry.is_symlink.return_value = True
		entry.is_dir.return_value = True

		self.assertTrue(_is_directory_link(entry))


class SettingsTest(TestCase):
	@patch('search_file_fuzzy.load_json')
	def test_invalid_values_use_defaults(self, load_json):
		load_json.return_value = {
			'mode': 'unknown',
			'max_recursive_entries': 0,
			'max_results': 'invalid',
			'include_hidden': 'false',
		}

		settings = _get_settings()

		self.assertEqual('fuzzy', settings['mode'])
		self.assertEqual(50_000, settings['max_recursive_entries'])
		self.assertEqual(100, settings['max_results'])
		self.assertIs(True, settings['include_hidden'])

	@patch('search_file_fuzzy.load_json', return_value={'mode': 'fuzzy'})
	def test_command_argument_overrides_configured_mode(self, load_json):
		self.assertEqual('regular', _get_settings('regular')['mode'])


class SearchCommandTest(TestCase):
	@patch('search_file_fuzzy.clear_status_message')
	@patch('search_file_fuzzy.show_status_message')
	@patch('search_file_fuzzy.show_quicksearch')
	@patch('search_file_fuzzy.build_index', side_effect=PermissionError('denied'))
	def test_inaccessible_root_reports_error_after_indexing_status_is_cleared(
		self, build_index_mock, show_quicksearch, show_status_message,
		clear_status_message
	):
		events = []
		show_status_message.side_effect = lambda message, **kwargs: \
			events.append(message)
		clear_status_message.side_effect = lambda: events.append('clear')
		pane = Mock()
		pane.get_path.return_value = as_url(r'C:\protected')

		SearchFilesInCurrentFolder(pane)()

		self.assertEqual(
			[
				'Indexing files...', 'clear',
				'Could not index C:\\protected: denied',
			],
			events
		)
		show_quicksearch.assert_not_called()

	@patch('search_file_fuzzy.clear_status_message')
	@patch('search_file_fuzzy.show_status_message')
	@patch('search_file_fuzzy.show_quicksearch')
	@patch('search_file_fuzzy.build_index')
	def test_selected_file_is_opened_in_its_directory(
		self, build_index_mock, show_quicksearch, show_status_message,
		clear_status_message
	):
		entry = SearchEntry(
			'file:///root/sub/report.txt', 'report.txt', 'sub/report.txt'
		)
		build_index_mock.return_value = IndexResult([entry], False)
		show_quicksearch.side_effect = lambda get_items, query='': (
			query, list(get_items('report'))[0].value
		)
		pane = Mock()
		pane.get_path.return_value = 'file:///root'

		SearchFilesInCurrentFolder(pane)()

		pane.run_command.assert_called_once_with(
			'open_directory', {'url': entry.url}
		)
		show_status_message.assert_called_once_with('Indexing files...')
		clear_status_message.assert_called_once_with()

	@patch('search_file_fuzzy.clear_status_message')
	@patch('search_file_fuzzy.show_status_message')
	@patch('search_file_fuzzy.show_quicksearch')
	@patch('search_file_fuzzy.build_index')
	def test_empty_index_does_not_open_quicksearch(
		self, build_index_mock, show_quicksearch, show_status_message,
		clear_status_message
	):
		build_index_mock.return_value = IndexResult([], False)
		pane = Mock()

		SearchFilesInCurrentFolder(pane)()

		show_quicksearch.assert_not_called()
		self.assertEqual(
			[
				(('Indexing files...',), {}),
				(('No files found.',), {'timeout_secs': 3}),
			],
			show_status_message.call_args_list
		)
		clear_status_message.assert_called_once_with()

	@patch('search_file_fuzzy.clear_status_message')
	@patch('search_file_fuzzy.show_status_message')
	@patch('search_file_fuzzy.show_quicksearch', return_value=None)
	@patch('search_file_fuzzy.build_index')
	def test_truncation_message_is_shown_after_quicksearch(
		self, build_index_mock, show_quicksearch, show_status_message,
		clear_status_message
	):
		entry = SearchEntry('file:///root/file.txt', 'file.txt', 'file.txt')
		build_index_mock.return_value = IndexResult([entry], True)
		events = []
		show_quicksearch.side_effect = lambda *args, **kwargs: \
			events.append('quicksearch')
		show_status_message.side_effect = lambda message, **kwargs: \
			events.append(message)
		pane = Mock()

		SearchFilesInCurrentFolder(pane)()

		self.assertEqual(
			[
				'Indexing files...', 'quicksearch',
				'Search limited to the first 50000 entries.',
			],
			events
		)