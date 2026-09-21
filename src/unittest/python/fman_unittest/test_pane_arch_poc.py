"""Functional checks for the pane architecture proof of concept."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless


SCRIPT = Path(__file__).resolve().parents[3] / 'misc' / 'pane_arch_poc.py'
SPEC = importlib.util.spec_from_file_location('pane_arch_poc', SCRIPT)
if SPEC is None or SPEC.loader is None:
	raise ImportError(str(SCRIPT))
poc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(poc)


class ListingTest(TestCase):
	def setUp(self):
		self._temporary = TemporaryDirectory()
		self.addCleanup(self._temporary.cleanup)
		self.root = Path(self._temporary.name)
		(self.root / 'file10.txt').write_bytes(b'0123456789')
		(self.root / 'file2.txt').write_bytes(b'01')
		(self.root / 'Zeta').mkdir()
		(self.root / 'alpha').mkdir()
		(self.root / '.dotfile').write_bytes(b'')

	def test_scan_collects_columns_without_following(self):
		listing = poc.Listing.scan(str(self.root))
		by_name = dict(zip(listing.names, zip(listing.is_dir, listing.sizes)))
		self.assertEqual({
			'file10.txt': (False, 10), 'file2.txt': (False, 2),
			'Zeta': (True, 0), 'alpha': (True, 0), '.dotfile': (False, 0),
		}, by_name)
		self.assertEqual(len(listing), 5)
		self.assertEqual([n.casefold() for n in listing.names], listing.lower_names)
		self.assertTrue(all(isinstance(m, int) for m in listing.mtimes_ns))

	def test_sort_puts_directories_first_and_uses_natural_order(self):
		listing = poc.Listing.scan(str(self.root))
		names = [listing.names[i] for i in poc.sort_order(listing, 'name')]
		self.assertEqual(['alpha', 'Zeta', '.dotfile', 'file2.txt', 'file10.txt'], names)
		descending = [listing.names[i] for i in poc.sort_order(listing, 'name', ascending=False)]
		self.assertEqual(['Zeta', 'alpha', 'file10.txt', 'file2.txt', '.dotfile'], descending)
		by_size = [listing.names[i] for i in poc.sort_order(listing, 'size')]
		self.assertEqual(['alpha', 'Zeta'], by_size[:2])
		self.assertEqual(['.dotfile', 'file2.txt', 'file10.txt'], by_size[2:])

	@skipUnless(sys.platform == 'win32', 'Windows hidden attribute')
	def test_hidden_attribute_comes_from_the_entry_itself(self):
		hidden = self.root / 'hidden.txt'
		hidden.write_bytes(b'x')
		subprocess.run(['attrib', '+h', str(hidden)], check=True, capture_output=True)
		listing = poc.Listing.scan(str(self.root))
		order = poc.sort_order(listing, 'name')
		self.assertIn('hidden.txt', listing.names)
		visible = [listing.names[i] for i in poc.hide_hidden(listing, order)]
		self.assertNotIn('hidden.txt', visible)
		self.assertIn('.dotfile', visible)


class FilterTest(TestCase):
	def _listing(self, names):
		return poc.Listing(
			'x', list(names), [False] * len(names), [0] * len(names), [0] * len(names),
			[0] * len(names), [n.casefold() for n in names]
		)

	def test_substring_is_case_insensitive_and_incremental_matches_full(self):
		names = ['Report2024.pdf', 'report_final.docx', 'notes.txt', 'REPO.md', 'x.rep']
		listing = self._listing(names)
		order = list(range(len(names)))
		filter_ = poc.Filter(listing, order)
		self.assertEqual(['Report2024.pdf', 'report_final.docx', 'REPO.md', 'x.rep'],
			[names[i] for i in filter_.apply('rep')])
		incremental = filter_.apply('repo')
		fresh = poc.Filter(listing, order).apply('repo')
		self.assertEqual(fresh, incremental)
		self.assertEqual(['Report2024.pdf', 'report_final.docx', 'REPO.md'], [names[i] for i in incremental])
		self.assertEqual(order, filter_.apply(''))

	def test_fuzzy_ranks_tighter_and_earlier_matches_first(self):
		names = ['a_b_c.txt', 'abc.txt', 'xxabcxx', 'zzz', 'a.b.c']
		listing = self._listing(names)
		result = poc.fuzzy(listing, range(len(names)), 'abc')
		self.assertEqual(['abc.txt', 'xxabcxx', 'a_b_c.txt', 'a.b.c'], [names[i] for i in result])

	def test_fuzzy_incremental_equals_full_and_mode_switch_restarts(self):
		names = ['%06d.jpg' % i for i in range(5000)]
		listing = self._listing(names)
		order = list(range(len(names)))
		filter_ = poc.Filter(listing, order)
		filter_.apply('19', 'fuzzy')
		incremental = filter_.apply('199', 'fuzzy')
		self.assertEqual(poc.fuzzy(listing, order, '199'), incremental)
		substring = filter_.apply('199', 'substring')
		self.assertEqual([i for i in order if '199' in names[i]], substring)

	def test_current_filter_preserves_grammar_unicode_and_edit_transitions(self):
		names = ['a', 'ab', 'b', 'Report.py', 'notes.txt', 'stra\u00dfe', '\u0131', '[ab']
		order = list(reversed(range(len(names))))
		filter_ = poc.CurrentFilter(self._listing(names), order)
		queries = ['!a', '!ab', '[ab', '[ab]', '^a', '*.py$', 'a?', r'\[ab',
			'ss', 'i', '', '!', '^', '$', 'x' * 256]
		for query in queries:
			with self.subTest(query=query):
				expected = [entry for entry in order if filter_.compile_filter(query).matches(names[entry])]
				self.assertEqual(expected, filter_.apply(query))
		self.assertNotIn(names.index('stra\u00dfe'), filter_.apply('ss'))
		self.assertIn(names.index('\u0131'), filter_.apply('i'))
		self.assertIn(names.index('a'), filter_.apply('!ab'))
		self.assertEqual([], filter_.apply('does-not-exist'))
		self.assertEqual(order, filter_.apply(''))

	def test_current_fuzzy_preserves_ranking_operators_limits_and_highlights(self):
		names = ['alpha', 'beta', 'a_b_c', 'abc', 'SecurityHealthHost.exe',
			'R\u00e9sum\u00e9_Annuel.pdf', 'stra\u00dfe', '\U0001f600report.txt', 'excluded']
		order = [7, 6, 5, 4, 3, 2, 1, 0]
		for limit in (1, 100, 0):
			filter_ = poc.CurrentFilter(self._listing(names), order, max_results=limit)
			for mode in ('fuzzy', 'regular'):
				direct = filter_.Matcher([
					filter_.SearchEntry(entry, names[entry], names[entry]) for entry in order
				], mode=mode, max_results=limit or len(order))
				for query in ('a', 'ab', '', '!alpha', '^alpha', "'beta", 'alpha | beta',
					'abc', 'scrty hlth', 'r\u00e9sm\u00e9 anel', 'ss', 'report', 'no-match'):
					with self.subTest(limit=limit, mode=mode, query=query):
						expected = direct.matches(query)
						self.assertEqual([entry.url for entry, positions in expected], filter_.apply(query, mode))
						self.assertEqual({entry.url: positions for entry, positions in expected}, filter_.highlights)
						self.assertNotIn(8, filter_.apply(query, mode))

	def test_current_fuzzy_never_reuses_truncated_results(self):
		filter_ = poc.CurrentFilter(self._listing(['a', 'ab', 'b']), [0, 1, 2], max_results=1)
		self.assertEqual([0], filter_.apply('a', 'fuzzy'))
		self.assertEqual([1], filter_.apply('ab', 'fuzzy'))
		self.assertEqual([2], filter_.apply('!a', 'fuzzy'))
		self.assertEqual([0], filter_.apply('!ab', 'fuzzy'))
		self.assertEqual([0, 1, 2], filter_.apply(''))
		self.assertEqual([1], filter_.apply('ab', 'fuzzy'))

	def test_current_fuzzy_candidates_can_differ_from_pane_visibility(self):
		filter_ = poc.CurrentFilter(self._listing(['visible', 'hidden', 'directory']),
			[0, 2], fuzzy_order=[0, 1])
		self.assertEqual([0, 2], filter_.apply(''))
		self.assertEqual([0, 1], filter_.apply('', 'fuzzy'))
		self.assertEqual([1], filter_.apply('hidden', 'fuzzy'))
		empty = poc.CurrentFilter(self._listing([]), [], max_results=0)
		self.assertEqual([], empty.apply(''))
		self.assertEqual([], empty.apply('a', 'fuzzy'))

	def test_current_fuzzy_adversarial_near_miss_is_bounded(self):
		code = (
			'import runpy; module = runpy.run_path(%r); name = "a" * 64; '
			'listing = module["Listing"]("x", [name], [False], [0], [0], [0], [name]); '
			'filter_ = module["CurrentFilter"](listing, [0]); '
			'assert filter_.apply("a" * 16 + "b", "fuzzy") == []'
		) % str(SCRIPT)
		subprocess.run([sys.executable, '-c', code], check=True, timeout=10,
			capture_output=True, text=True)


class ModelTest(TestCase):
	@classmethod
	def setUpClass(cls):
		os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
		from PyQt5.QtWidgets import QApplication
		cls.app = QApplication.instance() or QApplication([])

	def test_model_is_virtual_and_keeps_cursor_entry_across_filters(self):
		from PyQt5.QtCore import Qt
		names = ['b.txt', 'a.txt', 'dir', 'c.txt']
		listing = poc.Listing('x', names, [False, False, True, False], [1500, 2, 0, 3],
			[0, 0, 0, 0], [0, 0, 0, 0], [n.casefold() for n in names])
		order = poc.sort_order(listing, 'name')
		model = poc.build_model_class()(listing, order)
		self.assertEqual(4, model.rowCount())
		self.assertEqual('dir', model.data(model.index(0, 0), Qt.DisplayRole))
		self.assertEqual('', model.data(model.index(0, 1), Qt.DisplayRole))
		self.assertEqual('1.5 KB', model.data(model.index(2, 1), Qt.DisplayRole))
		self.assertRegex(model.data(model.index(1, 2), Qt.DisplayRole), r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$')
		cursor_entry = model.visible[2]  # b.txt
		model.set_visible(poc.Filter(listing, order).apply('b'))
		self.assertEqual(1, model.rowCount())
		self.assertEqual(0, model.row_of(cursor_entry))
		self.assertEqual(-1, model.row_of(model.listing.names.index('a.txt')))


class BenchmarkTest(TestCase):
	def test_cli_modes_measure_empty_results_and_keep_raw_timings(self):
		with TemporaryDirectory() as temporary:
			folder = Path(temporary) / 'files'
			folder.mkdir()
			(folder / 'alpha.txt').write_bytes(b'x')
			(folder / 'ab.txt').write_bytes(b'x')
			(folder / 'directory').mkdir()
			for mode in ('simple', 'current'):
				output = Path(temporary) / (mode + '.json')
				with self.subTest(mode=mode):
					subprocess.run([sys.executable, str(SCRIPT), str(folder),
						'--algorithms', mode, '--platform', 'offscreen', '--max-results', '1',
						'--fuzzy-scope', 'files', '--queries', 'a', 'no-match',
						'--fuzzy', 'a', 'ab', '--json', str(output)],
						check=True, capture_output=True, text=True, timeout=30)
					report = json.loads(output.read_text(encoding='utf-8'))
					self.assertEqual(mode, report['algorithms'])
					self.assertEqual(3, report['entries'])
					self.assertEqual(2, report['fuzzy_candidates'])
					self.assertEqual(mode == 'current', report['highlights_computed'])
					self.assertEqual(6, len(report['queries']))
					self.assertEqual(0, report['queries'][1]['rows'])
					for sample in report['queries']:
						self.assertGreaterEqual(sample['match_ms'], 0)
						self.assertGreater(sample['reset_paint_ms'], 0)
						self.assertAlmostEqual(sample['total_ms'], sample['match_ms'] + sample['reset_paint_ms'])
						if sample['mode'] == 'fuzzy':
							self.assertLessEqual(sample['rows'], 1)

	def test_cli_empty_folder_completes_paint(self):
		with TemporaryDirectory() as temporary:
			output = Path(temporary) / 'result.json'
			subprocess.run([sys.executable, str(SCRIPT), temporary, '--queries', '--fuzzy',
				'--json', str(output)], check=True, capture_output=True, text=True, timeout=30)
			report = json.loads(output.read_text(encoding='utf-8'))
			self.assertEqual(0, report['entries'])
			self.assertGreater(report['phases_ms']['scan_to_paint'], 0)
