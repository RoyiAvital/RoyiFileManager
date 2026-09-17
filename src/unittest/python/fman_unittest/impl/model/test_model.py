from fman.fs import Column
from fman.impl.model import Model, Cell
from fman.impl.model.model import File, _NOT_LOADED
from fman.impl.util.qt.thread import Executor
from fman.url import splitscheme
from fman_unittest.impl.model import StubFileSystem
from PyQt5.QtCore import QObject, pyqtSignal
from random import shuffle, random
from unittest import TestCase
from unittest.mock import Mock

import random

class ModelRecordFilesTest(TestCase):
	def test_reload_completion_after_shutdown_does_not_touch_rows(self):
		model = self._model
		previous = model._files
		model._shutdown = True
		model.update = Mock()
		model._on_files_reloaded([f('s://late', [c('late')])])
		self.assertIs(previous, model._files)
		model.update.assert_not_called()

	def test_refresh_filters_missing_and_foreign_rows_and_queues_async(self):
		model = self._model
		model._location = 's://'
		model._files = {'s://a': None}
		model._worker = Mock()
		model._load_files = Mock()
		model.refresh_files(('s://a', 's://a', 's://missing', 'other://a'))
		model._load_files.assert_not_called()
		priority, operation, target, urls = model._worker.submit.call_args.args
		operation(target, urls)
		model._load_files.assert_called_once_with(['s://a'])
	def test_load_file(self):
		f_not_loaded = f('s://a', [c('')], False)
		self._model._record_files([f_not_loaded])
		self._expect_data([('',)])
		f_loaded = f('s://a', [c('a')])
		self._model._record_files([f_loaded])
		self._expect_data([('a',)])
	def test_remove_file(self):
		self._model._record_files([f('s://a', [c('a')])])
		self._expect_data([('a',)])
		self._model._record_files([], ['s://a'])
		self._expect_data([])
	def test_remove_two_files(self):
		self._model._record_files([
			f('s://a', [c('a', 0)]),
			f('s://b', [c('b', 1)])
		])
		self._expect_data([('a',), ('b',)])
		self._model._record_files([], ['s://a', 's://b'])
		self._expect_data([])
	def test_remove_files_gap(self):
		self._model._record_files([
			f('s://a', [c('a', 0)]),
			f('s://b', [c('b', 1)]),
			f('s://c', [c('c', 2)]),
			f('s://d', [c('d', 3)]),
		])
		self._expect_data([('a',), ('b',), ('c',), ('d',)])
		self._model._record_files([], ['s://b', 's://d'])
		self._expect_data([('a',), ('c',)])
	def test_remove_files_out_of_order(self):
		self._model._record_files([
			f('s://a', [c('a', 0)]),
			f('s://b', [c('b', 1)]),
			f('s://c', [c('c', 2)])
		])
		self._expect_data([('a',), ('b',), ('c',)])
		self._model._record_files([], ['s://c', 's://b'])
		self._expect_data([('a',)])
	def test_complex(self):
		e = f('s://e', [c('e', 4)])
		self._model._record_files([
			f('s://a', [c('a', 0)]),
			f('s://b', [c('b', 1)]),
			f('s://d', [c('d', 2)]),
			e
		])
		self._expect_data([('a',), ('b',), ('d',), ('e',)])
		# Simulate e having fallen out of the filter:
		self._model._filters.append(lambda url: url != e.url)
		self._model._record_files([
			f('s://c', [c('c', 3)]),
			f('s://a', [c('a', 5)]),
			e
		], ['s://d'])
		self._expect_data([('b',), ('c',), ('a',)])
	def test_many_moves(self):
		files = [f('s://%d' % i, [c(str(i), i)]) for i in range(5)]
		self._model._record_files(files)
		self._expect_data([(str(i),) for i in range(5)])
		order_after = [4, 0, 3, 2, 1]
		self._model._record_files(
			[f('s://%d' % j, [c(str(j), i)]) for i, j in enumerate(order_after)]
		)
		self._expect_data([(str(i),) for i in order_after])
	def test_reverse(self, num=3):
		files = [f('s://%d' % i, [c(str(i), i)]) for i in range(num)]
		self._model._record_files(files)
		self._expect_data([(str(i),) for i in range(num)])
		new_files = [
			f('s://%d' % i, [c(str(i), j)])
			for j, i in enumerate(reversed(range(num)))
		]
		self._model._record_files(new_files)
		self._expect_data([(str(i),) for i in reversed(range(num))])
	def test_move_last(self):
		files = [f('s://%d' % i, [c(str(i), i)]) for i in range(3)]
		self._model._record_files(files)
		self._expect_data([(str(i),) for i in range(3)])
		order_after = [2, 0, 1]
		self._model._record_files(
			[f('s://%d' % j, [c(str(j), i)]) for i, j in enumerate(order_after)]
		)
		self._expect_data([(str(i),) for i in order_after])
	def test_file_disappeared(self):
		files = [f('s://%d' % i, [c(str(i), i)]) for i in range(4)]
		self._model._record_files(files)
		self._expect_data([(str(i),) for i in range(4)])
		new_files = [
			f('s://3', [c('3', 0)]),
			f('s://0', [c('0', 1)]),
			f('s://2', [c('2', 2)])
		]
		self._model._record_files(new_files, disappeared=['s://1'])
		self._expect_data([('3',), ('0',), ('2',)])
	def test_random(self):
		for num in list(range(6)) + [100]:
			self._test_random(num)
			self.tearDown()
			self.setUp()
	def _test_random(self, num=3):
		to_url = lambda i: 's://%d' % i
		from_url = lambda url: int(splitscheme(url)[1])
		files = [f(to_url(i), [c(str(i), i)]) for i in range(num)]
		self._model._record_files(files)
		self._expect_data([(str(i),) for i in range(num)])
		random_state = random.getstate()
		order = list(range(num))
		shuffle(order)
		filtered_out = {i for i in order if random.random() < .2}
		filter_ = lambda url: from_url(url) not in filtered_out
		disappeared = []
		for index in range(len(order) - 1, -1, -1):
			i = order[index]
			if i not in filtered_out and random.random() < .1:
				order.pop(index)
				disappeared.append(to_url(i))
		new_files = [f(to_url(j), [c(str(j), i)]) for i, j in enumerate(order)]
		self._model._filters.append(filter_)
		self._model._record_files(new_files, disappeared)
		message = 'num was %d, random.getstate() was %r' % (num, random_state)
		self._expect_data([
			(str(i),) for i in order if i not in filtered_out
		], message)
	def setUp(self):
		super().setUp()
		self._app = StubApp()
		self._executor_before = Executor._INSTANCE # Typically None
		Executor._INSTANCE = Executor(self._app)
		self._fs = StubFileSystem({})
		self._model = Model(self._fs, 'null://', [Column()])
		self.maxDiff = None
	def tearDown(self):
		self._app.aboutToQuit.emit()
		Executor._INSTANCE = self._executor_before
		super().tearDown()
	def _expect_data(self, expected, message=None):
		m = self._model
		actual = [
			tuple(m.data(m.index(i, j)) for j in range(m.columnCount()))
			for i in range(m.rowCount())
		]
		self.assertEqual(expected, actual, message)

class ModelSortTest(TestCase):
	def test_sort_loads_values_of_filtered_out_files(self):
		model = self._create_model()
		Model.sort.__wrapped__(model, 1)
		self._expect_data(model, [('c', '1'), ('a', '3')])
		model._filters.clear()
		model.update()
		self._expect_data(model, [('c', '1'), ('b', '2'), ('a', '3')])
	def test_sort_drops_filtered_out_file_that_disappeared(self):
		model = self._create_model(missing='s://b')
		Model.sort.__wrapped__(model, 1)
		self.assertNotIn('s://b', model._files)
		model._filters.clear()
		model.update()
		self._expect_data(model, [('c', '1'), ('a', '3')])
	def _create_model(self, missing=None):
		names = {'s://a': 'a', 's://b': 'b', 's://c': 'c'}
		numbers = {'s://a': '3', 's://b': '2', 's://c': '1'}
		columns = [StubColumn(names), StubColumn(numbers, missing)]
		model = Model(
			self._fs, 'null://', columns, filters=[lambda url: url != 's://b']
		)
		model._record_files([
			f(url, [c(names[url], names[url]), c(numbers[url], _NOT_LOADED)])
			for url in names
		])
		self._expect_data(model, [('a', '3'), ('c', '1')])
		return model
	def setUp(self):
		super().setUp()
		self._app = StubApp()
		self._executor_before = Executor._INSTANCE # Typically None
		Executor._INSTANCE = Executor(self._app)
		self._fs = StubFileSystem({})
	def tearDown(self):
		self._app.aboutToQuit.emit()
		Executor._INSTANCE = self._executor_before
		super().tearDown()
	def _expect_data(self, m, expected):
		actual = [
			tuple(m.data(m.index(i, j)) for j in range(m.columnCount()))
			for i in range(m.rowCount())
		]
		self.assertEqual(expected, actual)

class StubColumn(Column):
	def __init__(self, values, missing=None):
		super().__init__()
		self._values = values
		self._missing = missing
	def get_str(self, url):
		if url == self._missing:
			raise FileNotFoundError(url)
		return self._values[url]
def f(url, cells, is_loaded=False, is_dir=False):
	return File(url, None, is_dir, cells, is_loaded)

def c(str_, sort_value_asc=0, sort_value_desc=_NOT_LOADED):
	return Cell(str_, sort_value_asc, sort_value_desc)

class StubApp(QObject):
	aboutToQuit = pyqtSignal()