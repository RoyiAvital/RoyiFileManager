from types import SimpleNamespace
from unittest import TestCase

from PyQt5.QtCore import Qt

from fman.impl.model.sorted_table import SortFilterTableModel


class SortTest(TestCase):
	def test_persistent_indexes_follow_rows_without_repeated_lookup_passes(self):
		model = _Model()

		SortFilterTableModel.sort(model, 1, Qt.AscendingOrder)

		# One pass builds the lookup; the second resets the stored rows.
		self.assertEqual(2, model.new_rows.iterations)
		self.assertEqual([
			(model.indexes[0], (1, 0)),
			(model.indexes[1], (0, 1))
		], model.changed_indexes)


class _Model:
	VerticalSortHint = object()

	def __init__(self):
		self._sort_column = 0
		self._sort_ascending = True
		self._rows = _Rows([
			SimpleNamespace(key='b'), SimpleNamespace(key='a')
		])
		self.new_rows = _TrackedRows([
			SimpleNamespace(key='a'), SimpleNamespace(key='b')
		])
		self.indexes = (_Index(0, 0), _Index(1, 1))
		self.changed_indexes = []
		self.layoutAboutToBeChanged = _Signal()
		self.layoutChanged = _Signal()
		self.sort_order_changed = _Signal()

	def _sorted(self, rows):
		return self.new_rows

	def persistentIndexList(self):
		return self.indexes

	def index(self, row, column):
		return row, column

	def changePersistentIndex(self, old, new):
		self.changed_indexes.append((old, new))


class _Rows(list):
	def reset_to(self, rows):
		self[:] = rows


class _TrackedRows(list):
	def __init__(self, rows):
		super().__init__(rows)
		self.iterations = 0

	def __iter__(self):
		self.iterations += 1
		return super().__iter__()


class _Index:
	def __init__(self, row, column):
		self._row = row
		self._column = column

	def row(self):
		return self._row

	def column(self):
		return self._column


class _Signal:
	def emit(self, *args):
		pass