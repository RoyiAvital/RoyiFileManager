from fman.impl.view.resize_cols_to_contents import ResizeColumnsToContents, \
	_get_ideal_column_widths, _resize_column
from unittest import TestCase


class RowsVisibleButNotLoadedTest(TestCase):
	def test_has_stops_at_first_unloaded_row(self):
		view = _View([True, False, True])

		result = ResizeColumnsToContents._has_rows_visible_but_not_loaded(view)

		self.assertTrue(result)
		self.assertEqual([0, 1], view.model().checked_rows)

	def test_has_returns_false_when_all_visible_rows_are_loaded(self):
		view = _View([True, True])

		result = ResizeColumnsToContents._has_rows_visible_but_not_loaded(view)

		self.assertFalse(result)
		self.assertEqual([0, 1], view.model().checked_rows)

	def test_get_returns_unloaded_rows(self):
		view = _View([True, False, True, False])

		result = ResizeColumnsToContents._get_rows_visible_but_not_loaded(view)

		self.assertEqual([1, 3], result)

	def test_get_returns_empty_list_when_all_loaded(self):
		view = _View([True, True])

		result = ResizeColumnsToContents._get_rows_visible_but_not_loaded(view)

		self.assertEqual([], result)


class _View:
	def __init__(self, loaded):
		self._model = _Model(loaded)

	def model(self):
		return self._model

	def get_visible_row_range(self):
		return range(len(self._model.loaded))


class _Model:
	def __init__(self, loaded):
		self.loaded = loaded
		self.checked_rows = []

	def row_is_loaded(self, row):
		self.checked_rows.append(row)
		return self.loaded[row]

class GetIdealColumnWidthsTest(TestCase):
	def test_one_column_no_change(self):
		self._expect([1], [1], [1], 1)
	def test_one_column_truncated(self):
		self._expect([2], [1], [2], 2)
	def test_one_column_too_large(self):
		self._expect([1], [2], [1], 1)
	def test_two_cols(self):
		self._expect([2, 1], [1, 2], [2, 1], 3)
	def test_truncate_first_col(self):
		self._expect([400, 100], [500, 100], [500, 100], 500, delta_percent=3)
	def test_maximize_window(self):
		self._expect([2, 1], [1, 1], [1, 1], 3)
	def _expect(
		self, result, widths, min_widths, available_width, delta_percent=0
	):
		actual = \
			_get_ideal_column_widths(widths, min_widths, available_width)
		self.assertEqual(len(result), len(actual))
		if delta_percent:
			for r, a in zip(result, actual):
				if delta_percent:
					delta = int(r * delta_percent / 100)
					self.assertLessEqual(r - delta, a)
					self.assertGreaterEqual(r + delta, a)
		else:
			self.assertEqual(result, actual)

class ResizeColumnTest(TestCase):
	def test_enlarge(self):
		self._expect([2, 1, 1], 0, 2, [1, 2, 1], [1, 1, 1])
	def test_shrink(self):
		self._expect([1, 2, 1], 0, 1, [2, 1, 1], [1, 1, 1])
	def test_shrink_below_available_width(self):
		self._expect([1, 1, 2], 0, 1, [2, 1, 2], [1, 1, 2], 4)
	def test_shrink_last_but_one(self):
		self._expect([1, 1, 2], 1, 1, [1, 2, 1], [2, 1, 2])
	def test_enlarge_trims_last_col(self):
		self._expect([2, 1], 0, 2, [1, 2], [1, 1], 3)
	def test_rightalign_last_col(self):
		self._expect([1, 2, 1], 0, 1, [2, 1, 1], [1, 1, 1])
	def _expect(
		self, result, col, old_size, widths, min_widths, available_width=None
	):
		if available_width is None:
			available_width = sum(widths)
		actual = _resize_column(
			col, old_size, widths, min_widths, available_width
		)
		self.assertEqual(result, actual)