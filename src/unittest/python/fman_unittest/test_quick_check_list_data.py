from fman.impl.ui.check_list_data import CheckListItem, CheckListResult, MAX_ITEMS, \
	PRESETS, label, next_state, prepare, result
from itertools import count
from unittest import TestCase


def _prepare(items, states='checkbox3', **arguments):
	values = dict(title='', summary='', status='', filter=None, alternate=False)
	values.update(arguments)
	return prepare(items, states, **values)


class QuickCheckListDataTest(TestCase):
	def test_prepare_copies_items_and_reads_options(self):
		class Item(CheckListItem):
			pass
		source = Item('r', 'Read-only', 'mixed', 'R', 'Prevent changes')
		prepared = _prepare([source], status='Enter: Apply', filter='fuzzy', alternate=True)
		self.assertIs(CheckListItem, type(prepared.items[0]))
		self.assertEqual(CheckListItem('r', 'Read-only', 'mixed', 'R', 'Prevent changes'), prepared.items[0])
		self.assertEqual(PRESETS['checkbox3'], prepared.states)
		self.assertEqual(('Enter: Apply', True, True), (prepared.status, prepared.fuzzy, prepared.alternate))

	def test_prepare_rejects_invalid_options(self):
		item = CheckListItem('a', 'A', 'off')
		for states in ('radio', None, ('off', 'on')):
			with self.assertRaises(ValueError):
				_prepare([item], states)
		with self.assertRaises(ValueError):
			_prepare([item], filter='substring')
		with self.assertRaises(TypeError):
			_prepare([item], alternate=1)
		with self.assertRaises(TypeError):
			_prepare([item], title=None)
		with self.assertRaises(ValueError):
			_prepare([item], status='x' * 513)
		with self.assertRaises(ValueError):
			_prepare([item], summary='a\x00b')

	def test_prepare_rejects_invalid_items(self):
		cases = [
			([], ValueError), ('ab', TypeError), (5, TypeError), ([('a', 'A', 'off')], TypeError),
			([CheckListItem('', 'A', 'off')], ValueError),
			([CheckListItem('a', 'A', 'off'), CheckListItem('a', 'B', 'off')], ValueError),
			([CheckListItem('a', '', 'off')], ValueError),
			([CheckListItem('a', 'A', 'filled')], ValueError),
			([CheckListItem('a', 'A', None)], ValueError),
			([CheckListItem('a', 'A', 'off', enabled=1)], TypeError),
			([CheckListItem('a', 'A', 'off', hint=3)], TypeError),
			([CheckListItem('a' * 513, 'A', 'off')], ValueError),
			([CheckListItem('a', 'A' * 513, 'off')], ValueError),
			([CheckListItem('a', 'A', 'off', description='d' * 2049)], ValueError),
		]
		for items, error in cases:
			with self.subTest(items=repr(items)[:60]), self.assertRaises(error):
				_prepare(items)

	def test_prepare_bounds_item_count_and_text(self):
		endless = (CheckListItem(str(index), 'T', 'off') for index in count())
		with self.assertRaises(ValueError):
			_prepare(endless)
		self.assertEqual(MAX_ITEMS, len(_prepare(
			CheckListItem(str(index), 'T', 'off') for index in range(MAX_ITEMS)).items))
		# Each item holds 16 KiB of UTF-8: 300 items exceed the 4 MiB budget, 200 do not.
		large = [CheckListItem(str(index), 'T', 'off', '\U0001f600' * 2048, '\U0001f600' * 2048)
			for index in range(300)]
		with self.assertRaises(ValueError):
			_prepare(large)
		self.assertEqual(200, len(_prepare(large[:200]).items))

	def test_cycles_follow_the_ring_in_both_directions(self):
		states = PRESETS['checkbox3']
		self.assertEqual('on', next_state(states, 'off', 'off', 1))
		self.assertEqual('off', next_state(states, 'off', 'on', 1))
		self.assertEqual('on', next_state(states, 'off', 'off', -1))
		self.assertEqual('off', next_state(states, 'mixed', 'mixed', 1))
		self.assertEqual('on', next_state(states, 'mixed', 'off', 1))
		self.assertEqual('mixed', next_state(states, 'mixed', 'on', 1))
		self.assertEqual('on', next_state(states, 'mixed', 'mixed', -1))
		self.assertEqual('mixed', next_state(states, 'mixed', 'off', -1))
		self.assertEqual('filled', next_state(PRESETS['star'], 'empty', 'empty', 1))
		self.assertEqual('Mixed', label(states, 'mixed'))

	def test_result_reports_changed_items_only(self):
		items = (CheckListItem('a', 'A', 'off'), CheckListItem('b', 'B', 'mixed'),
			CheckListItem('c', 'C', 'on', enabled=False))
		current = {'a': 'on', 'b': 'mixed', 'c': 'on'}
		self.assertEqual(CheckListResult({'a': 'on'}, 'alternate'), result(items, current, 'alternate'))
		changed, approval = result(items, {'a': 'off', 'b': 'mixed', 'c': 'on'}, None)
		self.assertEqual(({}, None), (changed, approval))
