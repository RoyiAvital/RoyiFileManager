from pathlib import Path
from stat import FILE_ATTRIBUTE_HIDDEN
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch

from search_file_fuzzy import SearchFilesInCurrentFolder, SearchFilesRecursively, \
	_get_settings
from search_file_fuzzy.indexer import IndexResult, _is_directory_link, build_index
from search_file_fuzzy.matcher import Matcher, SearchEntry, normalize, _score, \
	_mapped_normalize
from search_file_fuzzy.query import Term, parse
from fman.url import as_url

import os
import shutil
import subprocess
import sys


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


class QueryTest(TestCase):
	def test_adjacent_or_terms_are_anded_with_other_sets(self):
		self.assertEqual((
			(Term('fuzzy', 'foo', False),),
			(Term('fuzzy', 'bar', False), Term('fuzzy', 'baz', False)),
		), parse('foo bar | baz'))

	def test_operators(self):
		for query, kind, text, negate in (
			("'report", 'exact', 'report', False),
			('^src', 'prefix', 'src', False),
			('.py$', 'suffix', '.py', False),
			('^file$', 'equal', 'file', False),
			('!tmp', 'exact', 'tmp', True),
			('!^src', 'prefix', 'src', True),
			('!.py$', 'suffix', '.py', True),
			("!'tmp", 'fuzzy', 'tmp', True),
			("'word'", 'boundary', 'word', False),
			("!'word'", 'boundary', 'word', True),
			('$', 'fuzzy', '$', False),
			("''", 'exact', "'", False),
			("'foo$", 'exact', 'foo', False),
		):
			with self.subTest(query=query):
				self.assertEqual(((Term(kind, text, negate),),), parse(query))

	def test_only_spaces_are_escaped(self):
		self.assertEqual(((Term('exact', 'two words', False),),),
			parse("'two\\ words"))
		self.assertEqual(((Term('fuzzy', r'\^src', False),),),
			parse(r'\^src'))
		self.assertEqual(((Term('fuzzy', 'end ', False),),),
			parse('end\\ '))
		self.assertEqual(((Term('fuzzy', 'two words', False),),),
			parse('two\twords'))

	def test_empty_terms_are_ignored(self):
		for query in ('', ' ', "'", '^', '!', '^$', '!^$', "!'"):
			with self.subTest(query=query):
				self.assertEqual((), parse(query))

	def test_partial_bars_follow_fzf(self):
		self.assertEqual(((Term('fuzzy', '|', False),),), parse('|'))
		self.assertEqual(((Term('fuzzy', 'foo', False),),), parse('foo |'))
		self.assertEqual((
			(Term('fuzzy', 'foo', False), Term('fuzzy', '|', False)),
			(Term('fuzzy', 'bar', False),),
		), parse('foo | | bar'))


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


class ExtendedMatcherTest(TestCase):
	paths = (
		'src/core.py', 'src/core.rb', 'docs/core.py', 'src/helper.pyc',
		'docs/annual report.pdf', 'tmp/report.pdf', 'word_word.txt',
		'sword.txt', 'word.txt', 'abbreviation.txt', 'a!b.txt',
		"Don't panic.txt", '$RECYCLE.BIN', 'two  words.txt',
	)

	def matcher(self, paths=None, **kwargs):
		paths = self.paths if paths is None else paths
		return Matcher([
			SearchEntry('file:///root/' + path, path.rsplit('/', 1)[-1], path)
			for path in paths
		], **kwargs)

	def test_syntax_match_sets(self):
		for query, expected in (
			("'report", {'docs/annual report.pdf', 'tmp/report.pdf'}),
			('^src .py$ | .rb$', {'src/core.py', 'src/core.rb'}),
			('^core', set()),
			('!tmp .pdf$', {'docs/annual report.pdf'}),
			('!^src .py$', {'docs/core.py'}),
			('!.py$ ^src', {'src/core.rb', 'src/helper.pyc'}),
			('^src\\core.py$', {'src/core.py'}),
			("'annual\\ report", {'docs/annual report.pdf'}),
			("'word'", {'word_word.txt', 'word.txt'}),
			("!'word' .txt$", {'sword.txt', 'abbreviation.txt', 'a!b.txt',
				"Don't panic.txt", 'two  words.txt'}),
			("!'abt .txt$", {'word_word.txt', 'sword.txt', 'word.txt',
				"Don't panic.txt", 'two  words.txt'}),
			("'a!b", {'a!b.txt'}),
			("'Don't", {"Don't panic.txt"}),
			('$RECYCLE', {'$RECYCLE.BIN'}),
		):
			with self.subTest(query=query):
				self.assertEqual(expected, {entry.relative_path for entry in self.matcher()(query)})

	def test_prefix_suffix_whitespace_and_escaped_spaces(self):
		matcher = self.matcher(['  file  ', 'file', 'file name', 'filename'])
		for query, count in [('^file$', 2), ('^\\ \\ file', 1),
			('file\\ \\ $', 1), ('file\\ name', 1)]:
			with self.subTest(query=query):
				self.assertEqual(count, len(matcher(query)))

	def test_every_query_prefix_is_safe(self):
		matcher = self.matcher()
		for query in ("^src .py$ | .rb$ !'tmp", "'annual\\ report", "!'word'", r'\^$'):
			for end in range(len(query) + 1):
				with self.subTest(query=query[:end]):
					matcher.matches(query[:end])

	def test_marker_only_queries_and_literal_dollar(self):
		matcher = self.matcher()
		for query in ("'", '^', '!', '^$', '!^$', "!'"):
			self.assertEqual(list(self.paths), [entry.relative_path for entry in matcher(query)])
		self.assertEqual(['$RECYCLE.BIN'], [entry.name for entry in matcher('$')])

	def test_ordinary_ranking_is_unchanged(self):
		matcher = self.matcher()
		for query in ('report pdf', 'src core', 'wrd txt', 'py', '', 'core.py'):
			normalized = normalize(query)
			scored = [(max(_score(normalized, normalize(entry.name), True),
				_score(normalized, normalize(entry.relative_path), False)), -index, entry)
				for index, entry in enumerate(matcher._entries)]
			expected = [entry for score, _, entry in sorted(scored, reverse=True)
				if score != float('-inf')] if normalized else matcher._entries
			self.assertEqual(expected, matcher(query))

	def test_filter_order_and_limit(self):
		matcher = self.matcher(max_results=2)
		self.assertEqual(matcher._entries[:2], matcher("'src"))
		self.assertEqual(matcher._entries[:2], matcher('!missing'))
		self.assertEqual(2, len(matcher('c | r')))

	def test_matching_and_highlighting_share_one_query_preparation(self):
		from search_file_fuzzy.matcher import _prepare
		matcher = self.matcher()
		for query in ('^src .py$ | .rb$', '!', "'annual\\ report"):
			with self.subTest(query=query):
				expected = matcher(query)
				with patch('search_file_fuzzy.matcher.parse', wraps=parse) as parser, \
					patch('search_file_fuzzy.matcher._prepare', wraps=_prepare) as prepare:
					matches = matcher.matches(query)
					parser.assert_called_once_with(query)
					prepare.assert_called_once()
				self.assertEqual(expected, [entry for entry, highlights in matches])

	def test_ordinary_and_regular_queries_do_not_parse_extended_syntax(self):
		for mode, query in (('fuzzy', 'report pdf'), ('regular', '!^src')):
			with self.subTest(mode=mode):
				matcher = self.matcher(mode=mode)
				expected = matcher(query)
				with patch('search_file_fuzzy.matcher.parse', side_effect=AssertionError('Unexpected parser')):
					self.assertEqual(expected, [entry for entry, highlights in matcher.matches(query)])

	def test_documented_use_cases(self):
		matcher = self.matcher([
			'docs/annual report.pdf', 'tmp/report.pdf', 'docs/annual-report.pdf',
			'src/core.py', 'src/tools/build.rb', 'src/tests/test_core.py',
			'docs/core.py', 'src/core.pyc', 'report_notes.txt', 'annualreport.txt',
			'backup.txt', '!important.txt', 'README.md', 'docs/README.md', 'notes.txt',
		])
		for query, expected in (
			('rpt pdf', {'docs/annual report.pdf', 'tmp/report.pdf', 'docs/annual-report.pdf'}),
			("'report .pdf$ !tmp", {'docs/annual report.pdf', 'docs/annual-report.pdf'}),
			('^src .py$ | .rb$ !test', {'src/core.py', 'src/tools/build.rb'}),
			("'annual\\ report .pdf$", {'docs/annual report.pdf'}),
			('^src\\core.py$', {'src/core.py'}),
			("'report' .txt$", {'report_notes.txt'}),
			(".txt$ !'bkp", {'report_notes.txt', 'annualreport.txt', '!important.txt', 'notes.txt'}),
			("'!important", {'!important.txt'}),
			('^README.md$', {'README.md'}),
		):
			with self.subTest(query=query):
				self.assertEqual(expected, {entry.relative_path for entry, highlights in matcher.matches(query)})

	def test_highlights_use_first_positive_or_term_and_not_negations(self):
		matcher = self.matcher(['foo bar'])
		for query, positions in [("'foo | 'bar", [0, 1, 2]),
			("!missing | 'bar", [4, 5, 6]), ('!missing', []),
			("'foo 'bar", [0, 1, 2, 4, 5, 6])]:
			with self.subTest(query=query):
				self.assertEqual(positions, matcher.matches(query)[0][1])

	def test_literal_and_fuzzy_highlights_map_to_utf16(self):
		for path, query, expected in (
			('docs/report.py', '.py$', [11, 12, 13]),
			('docs/report.py', 'rpt', [5, 7, 10]),
			('\U0001f600/report.txt', "'report", list(range(3, 9))),
			('\U0001f600/report.txt', "'\U0001f600", [0, 1]),
			('Stra\u00dfe.txt', "'strasse", list(range(6))),
			('re\u0301sume\u0301.txt', "'r\u00e9sum\u00e9", list(range(8))),
			('SecurityHealth.exe', 'scrty hlth', [0, 2, 4, 6, 7, 8, 11, 12, 13]),
		):
			with self.subTest(path=path, query=query):
				self.assertEqual(expected, self.matcher([path]).matches(query)[0][1])

	def test_mapped_normalization_matches_existing_normalizer(self):
		for text in ('SecurityHealth.exe', 'a___b', '\uff21\uff22.txt',
			'Stra\u00dfe.txt', 're\u0301sume\u0301.txt', '\u1100\u1161.txt',
			'\U0001f600/hello', '  a  ', '\ufb03.txt', ''):
			self.assertEqual(normalize(text), _mapped_normalize(text)[0])

	def test_regular_mode_keeps_its_old_operator_handling(self):
		matcher = self.matcher(mode='regular')
		self.assertEqual(matcher('src'), matcher('!^src'))
		self.assertTrue(all(not positions for _, positions in matcher.matches('src')))


@skipUnless(os.environ.get('FZF_REFERENCE_TESTS') == '1', 'Opt-in fzf reference check')
class FzfReferenceTest(TestCase):
	@classmethod
	def setUpClass(cls):
		cls.executable = shutil.which('fzf')
		if not cls.executable:
			raise RuntimeError('FZF_REFERENCE_TESTS=1 requires fzf on PATH')
		cls.environment = {key: value for key, value in os.environ.items()
			if not key.upper().startswith('FZF_')}
		cls.environment['FZF_DEFAULT_OPTS_FILE'] = os.devnull
		version = subprocess.run([cls.executable, '--version'],
			capture_output=True, check=True, timeout=10, env=cls.environment)
		print('\nfzf reference: ' + version.stdout.decode('utf-8').strip(), file=sys.stderr)

	def test_all_extended_syntax_against_installed_fzf(self):
		paths = ExtendedMatcherTest.paths + (
			'foo bar', 'foo baz', 'bar baz', 'foo|bar', 'foo | bar',
			'foo', 'foo.txt', 'a.b', 'a b', r'\^src', 'foo$',
			"'", '^', '!', '|', '$', '$$', '\\', ' file ', '  file  ',
			'file', 'file name', 'filename', 'file\t',
			'R\u00e9sum\u00e9.txt', '\U0001f600/file.py', 'foo_bar',
			'foobar', 'fooBar', 'foo1', 'foo-foo', 'foo.',
		)
		entries = [SearchEntry(str(index), path.rsplit('/', 1)[-1], path)
			for index, path in enumerate(paths)]
		matcher = Matcher(entries, max_results=len(entries))
		titles = [path.replace('/', '\\') for path in paths]
		payload = ('\0'.join(titles) + '\0').encode('utf-8')
		queries = {
			'', 'foo bar | baz', 'foo | bar baz', 'foo | | bar', '| foo',
			'foo |', '|', '$', '$$', '^$', '!^$', "''", "'''", '\\',
			r'\^src', '^src\\core.py$', "'annual\\ report", "'a!b",
			"'Don't", '$RECYCLE', 'file\\ name', '^\\ file',
			'file\\ $', '^file$', '^\\ \\ file', 'file\\ \\ $',
			'foo\tbar', "'R\u00c9SUM\u00c9", "'\U0001f600", "'foo$",
			'foo | !missing', '!missing | foo', 'foo !missing | bar',
		}
		for prefix in ('', '!', "'", "!'", '^', '!^'):
			for text in ('foo', 'bar', '.py', 'word', 'file'):
				for suffix in ('', '$', "'"):
					queries.add(prefix + text + suffix)
		for query in ("^src .py$ | .rb$ !'tmp", "'annual\\ report", "!'word'"):
			queries.update(query[:end] for end in range(len(query) + 1))
		for query in sorted(queries):
			with self.subTest(query=query):
				reference = subprocess.run([
					self.executable, '--extended', '--ignore-case', '--literal',
					'--no-sort', '--read0', '--print0', '--filter=' + query,
				], input=payload, capture_output=True, timeout=10, env=self.environment)
				self.assertIn(reference.returncode, (0, 1), reference.stderr.decode('utf-8'))
				expected = set(reference.stdout.decode('utf-8').rstrip('\0').split('\0')) \
					if reference.stdout else set()
				actual = {entry.relative_path.replace('/', '\\') for entry in matcher(query)}
				self.assertEqual(expected, actual)
		print('Compared %s queries against %s candidates.' % (len(queries), len(paths)),
			file=sys.stderr)


@skipUnless(os.environ.get('SEARCH_PERFORMANCE_TESTS') == '1', 'Opt-in performance check')
class SearchPerformanceTest(TestCase):
	def test_incremental_cost(self):
		from statistics import median
		from time import perf_counter
		cases = (
			('ordinary contiguous', 'report', 'report'),
			('ordinary subsequence', 'rpt', 'rpt'),
			('ordinary multi-term', 'report py', 'report py'),
			('contiguous + exclusion', 'report', 'report !missing'),
			('subsequence + exclusion', 'rpt', 'rpt !missing'),
			('subsequence + prefix', 'rpt', '^src rpt'),
		)
		for count in (1000, 10000, 50000):
			entries = [SearchEntry(str(index), 'report%05d.py' % index,
				'src/folder%03d/report%05d.py' % (index % 100, index))
				for index in range(count)]
			matcher = Matcher(entries)
			print('\nIncremental query cost: %s entries, milliseconds' % count, file=sys.stderr)
			for label, old_query, new_query in cases:
				def old():
					return matcher._fuzzy(normalize(old_query))
				def new():
					return matcher.matches(new_query)
				self.assertEqual(old(), [entry for entry, highlights in new()])
				timings = {'old': [], 'new': []}
				for repeat in range(9):
					operations = (('old', old), ('new', new))
					if repeat % 2:
						operations = operations[::-1]
					for name, operation in operations:
						started = perf_counter()
						found = operation()
						timings[name].append((perf_counter() - started) * 1000)
						self.assertLessEqual(len(found), 100)
				previous = median(timings['old'])
				current = median(timings['new'])
				delta = median([current_sample - previous_sample
					for previous_sample, current_sample in zip(timings['old'], timings['new'])])
				print('%-28s old=%7.2f new=%7.2f added=%+7.2f' %
					(label, previous, current, delta), file=sys.stderr)
			samples = {'regular': [], 'fuzzy': []}
			for repeat in range(11):
				modes = ('regular', 'fuzzy') if repeat % 2 else ('fuzzy', 'regular')
				for mode in modes:
					started = perf_counter()
					measured = Matcher(entries, mode=mode)
					elapsed = (perf_counter() - started) * 1000
					if repeat:
						samples[mode].append(elapsed)
					if mode == 'fuzzy':
						extra_bytes = sys.getsizeof(measured._literal_paths) + \
							sum(map(sys.getsizeof, measured._literal_paths))
					del measured
			delta = median([current - previous
				for previous, current in zip(samples['regular'], samples['fuzzy'])])
			print('Construction: without literal cache=%.2f with cache=%.2f added=%+.2f ms; cache=%.2f MiB' %
				(median(samples['regular']), median(samples['fuzzy']), delta, extra_bytes / 2**20),
				file=sys.stderr)

	def test_fifty_thousand_entries(self):
		from statistics import median
		from time import perf_counter
		import tracemalloc
		entries = [SearchEntry(str(index), 'report%05d.py' % index,
			'src/folder%03d/report%05d.py' % (index % 100, index))
			for index in range(50_000)]
		started = perf_counter()
		matcher = Matcher(entries)
		print('\nMatcher construction: %.1f ms' % ((perf_counter() - started) * 1000), file=sys.stderr)
		checks = [('old scoring baseline', lambda: matcher._fuzzy(normalize('report py')))]
		queries = ('report py', "'report", '^src', '.py$', '!tmp',
			"'missing", '^missing', '.missing$', '!report', '^src rpt',
			'^missing rpt', "'report rpt", 'r | p')
		checks.extend((query, lambda query=query: matcher.matches(query)) for query in queries)
		for name, operation in checks:
			operation()
			samples = []
			for repeat in range(7):
				started = perf_counter()
				found = operation()
				samples.append((perf_counter() - started) * 1000)
			self.assertLessEqual(len(found), 100)
			print('%-22s median=%7.2f ms max=%7.2f ms' %
				(name, median(samples), max(samples)), file=sys.stderr)
		tracemalloc.start()
		try:
			measured = Matcher(entries)
			current, peak = tracemalloc.get_traced_memory()
			self.assertEqual(100, len(measured('')))
			print('Matcher allocation: current=%.1f MiB peak=%.1f MiB' %
				(current / 2**20, peak / 2**20), file=sys.stderr)
		finally:
			tracemalloc.stop()


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
	@patch('search_file_fuzzy.load_json', return_value={})
	@patch('search_file_fuzzy.clear_status_message')
	@patch('search_file_fuzzy.show_status_message')
	@patch('search_file_fuzzy.show_quicksearch')
	@patch('search_file_fuzzy.build_index')
	def test_repeated_queries_reuse_index_and_supply_highlights(
		self, build_index_mock, show_quicksearch, show_status_message,
		clear_status_message, load_json
	):
		entry = SearchEntry('file:///root/src/report.py', 'report.py', 'src/report.py')
		build_index_mock.return_value = IndexResult([entry], False)
		def search(get_items, query=''):
			with patch('search_file_fuzzy.indexer.os.scandir', side_effect=AssertionError('Query I/O')):
				for current_query in ('^src .py$', "'report", '!', 'report'):
					items = list(get_items(current_query))
					self.assertEqual([entry.url], [item.value for item in items])
					self.assertEqual('src\\report.py', items[0].title)
					self.assertEqual(bool(current_query != '!'), bool(items[0].highlight))
				self.assertEqual([], list(get_items('!report')))
			return None
		show_quicksearch.side_effect = search
		for command, recursive in ((SearchFilesInCurrentFolder, False), (SearchFilesRecursively, True)):
			with self.subTest(command=command.__name__):
				build_index_mock.reset_mock()
				pane = Mock()
				pane.get_path.return_value = 'file:///root'
				command(pane)()
				build_index_mock.assert_called_once_with('file:///root', recursive=recursive,
					max_entries=50000, include_hidden=True)
				pane.run_command.assert_not_called()

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