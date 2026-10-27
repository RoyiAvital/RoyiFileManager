from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from time import sleep
from unittest import TestCase

from _quick_view_csv_worker import CsvError, Canceled, Engine, cache_quota, fold_pattern, labels, quote_tsv


LIMIT = 2048 * 1000 * 1000


class EngineTest(TestCase):
	def setUp(self):
		temporary = TemporaryDirectory()
		self.addCleanup(temporary.cleanup)
		self.root = Path(temporary.name)
		self.engine = Engine(str(self.root / 'cache'))
		self.addCleanup(self.engine.release)
		self.previews = []

	def write(self, data, name='data.csv'):
		path = self.root / name
		path.write_bytes(data if isinstance(data, bytes) else data.encode('utf-8'))
		return str(path)

	def open(self, data, name='data.csv', limit=LIMIT, memory=192, **options):
		self.engine.begin(1)
		self.previews.clear()
		return self.engine.open(self.write(data, name), limit, memory, options,
			lambda kind, header, payload: self.previews.append((kind, header, payload)))

	def all_rows(self):
		header, payload = self.engine.page(0, 1000)
		return [(row[0], row[1]) for row in payload['rows']]

	def test_strings_quotes_newlines_and_empty_fields(self):
		result = self.open('id,name,empty\r\n007,"a,b",\r\n2,"x""y",""\r\n3,"multi\nline",NULL\r\n\r\n4,,\r\n')
		self.assertEqual({'count': 4}, result)
		self.assertEqual([(1, ['007', 'a,b', '']), (2, ['2', 'x"y', '']), (3, ['3', 'multi\nline', 'NULL']),
			(4, ['4', '', ''])], self.all_rows())
		kind, header, payload = self.previews[0]
		self.assertEqual('preview', kind)
		self.assertEqual(['id', 'name', 'empty'], header['labels'])
		self.assertEqual(',', header['delimiter'])
		self.assertEqual(self.all_rows(), [(row[0], row[1]) for row in payload['rows']])

	def test_faults_are_rejected_not_repaired(self):
		for data, kind in (('a,b\n1,2\n3\n', 'parse'), ('a,b\n1,2,3\n', 'parse'), ('a,b\n1,"open\n2,3\n', 'parse'),
				(b'a,b\n1,x\x00y\n', 'limit'), (b'a,b\n1,\xff\xfe\n', None)):
			with self.subTest(data=data), self.assertRaises(CsvError) as raised:
				self.open(data, delimiter='comma', header='yes')
			if kind is not None:
				self.assertEqual(kind, raised.exception.kind)
			self.assertIsNone(self.engine.connection)

	def test_tsv_follows_strict_quoted_rules(self):
		data = 'id\ttitle\n1\t"Dune" by Herbert\n2\tplain\n'
		for options in ({}, {'delimiter': 'tab', 'header': 'yes'}):
			with self.subTest(options=options), self.assertRaises(CsvError) as raised:
				self.open(data, name='books.tsv', **options)
			self.assertEqual('parse', raised.exception.kind)
			self.assertIn('strict CSV rules', str(raised.exception))
			self.assertNotIn('search space', str(raised.exception))
		self.open('id\tsize\n1\t27" monitor\n2\t"a\tb"\n', name='sizes.tsv')
		self.assertEqual([(1, ['1', '27" monitor']), (2, ['2', 'a\tb'])], self.all_rows())

	def test_encodings(self):
		self.open(b'a,b\n1,caf\xe9\n', encoding='latin-1', delimiter='comma', header='yes')
		self.assertEqual([(1, ['1', 'caf\u00e9'])], self.all_rows())
		with self.assertRaises(CsvError) as raised:
			self.open(b'a,b\n1,\x80uro\n', encoding='latin-1', delimiter='comma', header='yes')
		self.assertEqual('encoding', raised.exception.kind)
		with self.assertRaises(CsvError):
			self.open(b'a,b\n1,\x93quoted\x94\n', delimiter='comma', header='yes')
		self.open(b'\xff\xfe' + 'a,b\n1,\u00e9\u20ac\n'.encode('utf-16-le'), delimiter='comma', header='yes')
		self.assertEqual([(1, ['1', '\u00e9\u20ac'])], self.all_rows())
		self.assertEqual('utf-16', self.previews[0][1]['encoding'])
		with self.assertRaises(CsvError) as raised:
			self.open(b'\xfe\xff' + 'a,b\n1,2\n'.encode('utf-16-be'))
		self.assertEqual('encoding', raised.exception.kind)
		with self.assertRaises(CsvError):
			self.open('a,b\n1,2\n', encoding='utf-16')
		self.open(b'\xef\xbb\xbfname,value\n1,2\n')
		self.assertEqual(['name', 'value'], self.previews[0][1]['labels'])

	def test_dialects_headers_and_labels(self):
		self.open('x;y\n1;2\n3;4\n')
		self.assertEqual(';', self.previews[0][1]['delimiter'])
		self.assertEqual([(1, ['1', '2']), (2, ['3', '4'])], self.all_rows())
		self.open('a\tb\n1\t2\n', name='data.tsv')
		self.assertEqual('\t', self.previews[0][1]['delimiter'])
		self.open('a|b\n1|2\n', delimiter='pipe', header='no')
		self.assertEqual(['Column 1', 'Column 2'], self.previews[0][1]['labels'])
		self.assertEqual([(1, ['a', 'b']), (2, ['1', '2'])], self.all_rows())
		self.open('a,,A,a\n1,2,3,4\n', delimiter='comma', header='yes')
		self.assertEqual(['a', 'Column 2', 'A (2)', 'a (3)'], self.previews[0][1]['labels'])
		self.assertEqual(['x', 'Column 2', 'x (2)'], labels(['x', None, 'x']))

	def test_limits(self):
		with self.assertRaises(CsvError) as raised:
			self.open('a,b\n1,2\n', limit=3)
		self.assertEqual('limit', raised.exception.kind)
		with self.assertRaises(CsvError) as raised:
			self.open(','.join('c%d' % index for index in range(257)) + '\n', delimiter='comma', header='yes')
		self.assertIn('256 columns', str(raised.exception))
		self.open(','.join('c%d' % index for index in range(256)) + '\n' + ','.join('1' * 256) + '\n', delimiter='comma', header='yes')
		self.assertEqual(256, len(self.previews[0][1]['labels']))
		self.assertEqual(16 * 1024 * 1024, cache_quota(0))
		self.assertEqual(4096000000, cache_quota(2048000000))
		self.assertEqual(8 * 1024 ** 3, cache_quota(10 ** 12))

	def test_long_fields_are_elided_only_for_display(self):
		value = 'x' * 600
		self.open('a,b\n1,%s\n' % value, delimiter='comma', header='yes')
		row = self.engine.page(0, 10)[1]['rows'][0]
		self.assertEqual(512, len(row[1][1]))
		self.assertEqual([1], row[2])
		self.assertEqual(value, self.engine.cell(0, 1)[1]['text'])
		self.assertEqual(value, self.engine.copy([0, 1], [1], False, [])[1]['text'])

	def test_native_queries_match_quicktable_predicates(self):
		from fman.impl.ui.table_data import QuickTableColumn
		from fman.impl.ui.table_filters import compile_filter
		values = ['Stra\u00dfe', 'STRASSE', '\u03a3\u0391\u03a3', '\u03c3\u03b1\u03c2', '\ufb01le', 'file', '100%', 'a_b',
			'back\\slash', 'quote"d', 'line\nbreak', 'e\u0301', '\u00e9', '\U0001f600 smile', '', 'aab', 'abab', 'Zeta', 'zeta']
		data = 'value,other\n' + ''.join('"%s",%d\n' % (value.replace('"', '""'), index % 3) for index, value in enumerate(values))
		self.open(data, delimiter='comma', header='yes')
		column = QuickTableColumn('value')
		class Row:
			def __init__(self, cells):
				self.cells = cells
		for operator in ('fuzzy', 'substring'):
			for query in ('ss', 'strasse', '\u03c3', 'fi', '%', '_', '\\', '"', 'ab', 'aa', '\U0001f600',
					'e', '\u00e9', '\u0301', 'Z', ' smile '):
				with self.subTest(operator=operator, query=query):
					predicate = compile_filter(column, 0, operator, query).predicate
					expected = [index + 1 for index, value in enumerate(values) if predicate(Row((value,)))]
					self.engine.begin(2)
					count = self.engine.query([[0, operator, query]], '', None)['count']
					rows = self.engine.page(0, 1000)[1]['rows']
					self.assertEqual(expected, [row[0] for row in rows])
					self.assertEqual(len(expected), count)
		self.engine.query([], 'STRASSE', None)
		self.assertEqual([1, 2], [row[0] for row in self.engine.page(0, 100)[1]['rows']])
		self.engine.query([[1, 'substring', '1']], 'a', None)
		self.assertEqual([index + 1 for index, value in enumerate(values) if index % 3 == 1 and 'a' in value.casefold() + str(index % 3)],
			[row[0] for row in self.engine.page(0, 100)[1]['rows']])
		for descending in (False, True):
			self.engine.query([], '', [0, descending])
			expected = [position + 1 for position in sorted(range(len(values)), key=lambda index: values[index].casefold(), reverse=descending)]
			self.assertEqual(expected, [row[0] for row in self.engine.page(0, 100)[1]['rows']])
		self.engine.query([], '', [1, True])
		self.assertEqual([3, 6, 9, 12, 15, 18, 2, 5, 8, 11, 14, 17, 1, 4, 7, 10, 13, 16, 19],
			[row[0] for row in self.engine.page(0, 100)[1]['rows']])
		self.assertEqual({0}, self.engine.folded & {0})
		self.engine.query([], '', None)
		self.assertEqual(len(values), self.engine.size)
		with self.assertRaises(CsvError):
			self.engine.query([[0, 'fuzzy', '   ']], '', None)

	def test_page_copy_cell_and_find_follow_the_projection(self):
		self.open('name,note\nbeta,"x\ty"\nalpha,plain\ngamma,"say ""hi"""\n', delimiter='comma', header='yes')
		self.engine.query([], '', [0, False])
		self.assertEqual([2, 1, 3], [row[0] for row in self.engine.page(0, 10)[1]['rows']])
		self.assertEqual('name\tnote\r\nalpha\tplain\r\nbeta\t"x\ty"',
			self.engine.copy([0, 2], [0, 1], True, ['name', 'note'])[1]['text'])
		self.assertEqual('say "hi"', self.engine.cell(2, 1)[1]['text'])
		self.assertEqual({'position': 2, 'column': 1, 'wrapped': False},
			self.engine.find('HI', None, False, 0, 1, False)[0])
		self.assertEqual({'position': 0, 'column': 0, 'wrapped': True},
			self.engine.find('ALPHA', None, False, 2, 1, False)[0])
		self.assertEqual(-1, self.engine.find('hi', None, True, 0, 0, False)[0]['position'] if False else
			self.engine.find('HI', None, True, 0, 0, False)[0]['position'])
		self.assertEqual(2, self.engine.find('hi', 1, True, 0, 0, False)[0]['position'])
		self.assertEqual({'position': 1, 'column': 1, 'wrapped': False}, self.engine.find('x', None, False, 2, 1, True)[0])
		self.assertEqual('a\t"b\nc"\t"q""u"', '\t'.join(quote_tsv(value) for value in ('a', 'b\nc', 'q"u')))

	def test_fold_pattern_escapes_like_wildcards(self):
		self.assertEqual('%a%\\%%\\_%\\\\%', fold_pattern('A%_\\'))
		self.assertEqual('%s%s%', fold_pattern('\u00df'))

	def test_interrupt_cancels_running_query(self):
		rows = ''.join('%d,%s\n' % (index, 'value%d' % index) for index in range(200000))
		self.open('a,b\n' + rows, delimiter='comma', header='yes')
		self.engine.begin(5)
		def stop():
			sleep(.05)
			self.engine.interrupt(5)
		thread = Thread(target=stop)
		thread.start()
		try:
			with self.assertRaises(Canceled):
				for _ in range(200):
					self.engine.query([[1, 'fuzzy', 'v%d' % _]], 'value', [1, _ % 2 == 0])
		finally:
			thread.join()
		self.engine.begin(6)
		self.assertEqual(200000, self.engine.query([], '', None)['count'])
		self.engine.interrupt(7)
		self.engine.begin(7)
		with self.assertRaises(Canceled):
			self.engine.check()

	def test_release_removes_owned_cache(self):
		self.open('a\n1\n', delimiter='comma', header='yes')
		directory = Path(self.engine.directory)
		self.assertTrue((directory / 'table.duckdb').exists())
		self.engine.release()
		self.assertFalse(directory.exists())

	def test_open_uses_only_a_new_requested_cache_folder(self):
		root = self.root / 'cache'
		requested = root / 's-1-requested'
		self.engine.begin(1)
		self.engine.open(self.write('a\n1\n'), LIMIT, 192, {}, lambda *args: None, str(requested))
		self.assertEqual(str(requested), self.engine.directory)
		self.assertTrue((requested / 'table.duckdb').exists())
		self.engine.release()
		(root / 's-2-existing').mkdir()
		for directory in (str(self.root / 's-3-outside'), str(root / 'x-4-prefix'), str(root / 's-2-existing'), 5):
			with self.subTest(directory=directory), self.assertRaises(CsvError) as raised:
				self.engine.open(self.write('a\n1\n'), LIMIT, 192, {}, lambda *args: None, directory)
			self.assertEqual('access', raised.exception.kind)
		self.assertTrue((root / 's-2-existing').is_dir())

	def test_canceled_fold_is_rolled_back_and_retried(self):
		data = 'a,b\n' + ''.join('%d,v\u00e9%d\n' % (index, index) for index in range(50))
		# Call 2 follows the column creation, call 3 is inside the staging loop.
		for failing_call in (2, 3):
			with self.subTest(failing_call=failing_call):
				self.open(data, delimiter='comma', header='yes')
				calls, check = [], self.engine.check
				def interrupted():
					calls.append(1)
					if len(calls) == failing_call:
						raise Canceled()
					check()
				self.engine.check = interrupted
				with self.assertRaises(Canceled):
					self.engine.query([[1, 'substring', 'V\u00c91']], '', None)
				del self.engine.check
				self.assertNotIn(1, self.engine.folded)
				self.assertEqual([], list(Path(self.engine.directory).glob('fold-*.csv')))
				self.assertEqual(11, self.engine.query([[1, 'substring', 'V\u00c91']], '', None)['count'])

	def test_long_values_are_bounded_before_python_allocation(self):
		import tracemalloc
		value = '\u00e9' * 70000
		self.open('a,b\n' + ''.join('%d,%s\n' % (index, value) for index in range(200)), delimiter='comma', header='yes')
		self.assertEqual(200, len(self.previews[0][2]['rows']))
		def peak(work):
			tracemalloc.start()
			try:
				result = work()
				return result, tracemalloc.get_traced_memory()[1]
			finally:
				tracemalloc.stop()
		(header, payload), used = peak(lambda: self.engine.page(0, 100))
		self.assertEqual(100, header['count'])
		self.assertEqual([1], payload['rows'][0][2])
		self.assertLess(used, 2 * 1024 * 1024)
		with self.assertRaises(CsvError) as raised:
			peak(lambda: self.engine.copy([0, 200], [1], False, []))
		self.assertIn('8 MiB', str(raised.exception))
		# Incompressible long non-ASCII values need about 3x the file size while folding.
		self.engine.quota = 10 ** 10
		result, used = peak(lambda: self.engine.query([[1, 'substring', '\u00c9']], '', None))
		self.assertEqual(200, result['count'])
		self.assertLess(used, 4 * 1024 * 1024)

	def test_wide_rows_return_short_pages_that_continue(self):
		width = 256
		row = ','.join('x' * 512 for _ in range(width))
		self.open(','.join('c%d' % index for index in range(width)) + '\n' + ''.join(row + '\n' for _ in range(20)),
			delimiter='comma', header='yes')
		self.engine.query([], '', [0, True])
		first = self.engine.page(0, 100)[0]['count']
		self.assertLess(first, 20)
		rest = self.engine.page(first, 100 - first)[1]['rows']
		self.assertEqual(20 - first, len(rest))

	def test_quota_is_enforced_before_and_after_work(self):
		from _quick_view_csv_worker import directory_size
		self.open('a,b\n1,2\n', delimiter='comma', header='yes')
		directory = Path(self.engine.directory)
		self.engine.quota = directory_size(str(directory)) + 1024
		with self.assertRaises(CsvError) as raised:
			self.engine._run(lambda: (directory / 'grown.bin').write_bytes(b'x' * 4096))
		self.assertEqual('resource', raised.exception.kind)
		self.assertIn('quota', str(raised.exception))
		with self.assertRaises(CsvError) as raised:
			self.engine.page(0, 10)
		self.assertEqual('resource', raised.exception.kind)

	def test_default_detection_accepts_supported_long_records(self):
		value = 'x' * 900000
		self.open('a,b,c\n%s,%s,%s\n1,2,3\n' % (value, value, value))
		self.assertEqual(',', self.previews[0][1]['delimiter'])
		self.assertEqual(2, self.engine.count)
		self.assertEqual(value, self.engine.cell(0, 2)[1]['text'])


class ControllerModelTest(TestCase):
	def setUp(self):
		from PyQt5.QtWidgets import QApplication
		self.app = QApplication.instance() or QApplication([])

	def test_record_count_estimate_keeps_the_number_column_width(self):
		from fman.impl.quick_view_csv import CsvPreview
		rows = [[index + 1, ['%06d' % index, '0.123456', 'x' * 20], []] for index in range(200)]
		record = sum(len(cell) + 1 for cell in rows[0][1])
		for count in (200, 284807, 10 ** 7):
			with self.subTest(count=count):
				header = dict(fingerprint=[0, 0, 40 + count * record, 0], encoding='utf-8')
				estimate = CsvPreview._estimate_count(header, rows)
				self.assertEqual(len(format(count, ',')), len(format(estimate, ',')))
		self.assertEqual(3, CsvPreview._estimate_count({}, rows[:3]))

	def test_actions_do_not_cross_query_revisions(self):
		from fman.impl.quick_view_csv import CsvController
		controller = CsvController()
		self.addCleanup(controller.deleteLater)
		done = []
		controller.action_done.connect(lambda *values: done.append(values))
		controller._ready, controller._generation, controller._revision = True, 1, 1
		controller._active = dict(type='copy', epoch=0, generation=1, operation=1, revision=1)
		controller.action(1, 'cell', position=3, column=0)
		controller.query(1, 2, [], 'x', None)
		self.assertIsNone(controller._action)
		controller._receive(dict(type='copy', epoch=0, generation=1, operation=1, revision=1), b'old')
		self.assertEqual([], done)

	def test_copy_text_arrives_as_raw_utf8(self):
		from fman.impl.quick_view_csv import CsvController
		controller = CsvController()
		self.addCleanup(controller.deleteLater)
		done = []
		controller.action_done.connect(lambda *values: done.append(values))
		controller._ready, controller._generation, controller._revision = True, 1, 1
		controller._active = dict(type='copy', epoch=0, generation=1, operation=1, revision=1)
		text = '\x01\u00e9\t"x"\r\n'
		controller._receive(dict(type='copy', epoch=0, generation=1, operation=1, revision=1), text.encode('utf-8'))
		self.assertEqual({'text': text}, done[0][3])

	def test_filter_typing_keeps_a_query_that_prepares_needed_folds(self):
		from unittest.mock import patch
		from fman.impl.quick_view_csv import CsvController
		controller = CsvController()
		self.addCleanup(controller.deleteLater)
		projected = []
		controller.projected.connect(lambda *values: projected.append(values))
		controller._ready, controller._generation, controller._revision, controller._columns = True, 1, 1, 3
		def active(filters, text='', sort=None, revision=1):
			controller._active = dict(type='query', epoch=0, generation=1, operation=1, revision=revision,
				filters=filters, text=text, sort=sort)
		with patch.object(controller, '_cancel') as cancel, patch.object(controller, '_pump'):
			for running, (filters, text), folded, canceled in (
					(([[1, 'fuzzy', 'a']], ''), ([[1, 'fuzzy', 'ab']], ''), set(), False),
					(([[1, 'fuzzy', 'a']], ''), ([[1, 'fuzzy', 'ab']], 'x'), set(), False),
					(([[1, 'fuzzy', 'a']], ''), ([[1, 'fuzzy', 'ab']], ''), {1}, True),
					(([[1, 'fuzzy', 'a']], ''), ([[2, 'fuzzy', 'ab']], ''), set(), True),
					(([], 'a'), ([[1, 'fuzzy', 'ab']], ''), set(), True)):
				with self.subTest(running=running, filters=filters, text=text, folded=folded):
					cancel.reset_mock()
					controller._folded = set(folded)
					active(*running)
					controller.query(1, controller._revision + 1, filters, text, None)
					self.assertEqual(canceled, cancel.called)
			active([[1, 'fuzzy', 'a']], revision=controller._revision - 1)
			controller._receive(dict(type='projection', epoch=0, generation=1, operation=1,
				revision=controller._revision - 1, count=5, folded=[1]), b'')
		self.assertEqual({1}, controller._folded)
		self.assertEqual([], projected)

	def test_model_requests_the_rest_of_a_short_page(self):
		from fman.impl.quick_view_csv import CsvModel
		model = CsvModel(None)
		requests = []
		model.request = requests.append
		model.reset(['a'], 20)
		self.assertIsNone(model.row(15))
		model.add_page(0, [[index + 1, ['r%d' % index], []] for index in range(10)])
		self.assertIsNone(model.row(15))
		self.assertEqual([0, 10], requests)
		model.add_page(10, [[index + 1, ['r%d' % index], []] for index in range(10, 20)])
		self.assertEqual(('r15',), model.row(15).cells)
		self.assertEqual('16', model.headerData(15, 2))
		model.add_page(25, [[26, ['stale'], []]])
		self.assertEqual(20, len(model.pages[0]))
