"""Qt-free validation, presets and state cycling for show_quick_check_list."""

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import islice
from typing import NamedTuple

from fman.impl.ui.table_data import text


MAX_ITEMS = 1000
MAX_ID = 512
MAX_TITLE = 512
MAX_HINT = 2048
MAX_DESCRIPTION = 2048
MAX_SUMMARY = 2048
MAX_STATUS = 512
MAX_TEXT_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class CheckListItem:
	id: str
	title: str
	state: str
	hint: str = ''
	description: str = ''
	enabled: bool = True


class CheckListResult(NamedTuple):
	# Item ID -> final state ID, for changed items only.
	changed: dict
	# 'primary', 'alternate' or None when cancelled.
	approval: str | None


@dataclass(frozen=True)
class State:
	id: str
	label: str
	# False: start-only, reachable only on items that started in it.
	cycle: bool = True


PRESETS = {
	'checkbox': (State('off', 'Off'), State('on', 'On')),
	'checkbox3': (State('off', 'Off'), State('on', 'On'), State('mixed', 'Mixed', cycle=False)),
	'star': (State('empty', 'Not starred'), State('filled', 'Starred')),
}


@dataclass(frozen=True)
class Prepared:
	preset: str
	states: tuple
	items: tuple
	title: str
	summary: str
	status: str
	fuzzy: bool
	alternate: bool


def _size(value):
	return len(value.encode('utf-8', 'surrogatepass'))


def prepare(items, states, title, summary, status, filter, alternate):
	if not isinstance(states, str) or states not in PRESETS:
		raise ValueError("states must be 'checkbox', 'checkbox3' or 'star'.")
	text(title, 'Title', MAX_TITLE)
	text(summary, 'Summary', MAX_SUMMARY)
	text(status, 'Status', MAX_STATUS)
	if filter not in ('fuzzy', None):
		raise ValueError("filter must be 'fuzzy' or None.")
	if type(alternate) is not bool:
		raise TypeError('alternate must be True or False.')
	if isinstance(items, (str, bytes)) or not isinstance(items, Iterable):
		raise TypeError('items must be an iterable of CheckListItem.')
	items = tuple(islice(items, MAX_ITEMS + 1))
	if not items or len(items) > MAX_ITEMS:
		raise ValueError('A QuickCheckList holds 1-%d items.' % MAX_ITEMS)
	known = {state.id for state in PRESETS[states]}
	ids = set()
	size = _size(title) + _size(summary) + _size(status)
	copies = []
	for item in items:
		if not isinstance(item, CheckListItem):
			raise TypeError('items must contain CheckListItem records.')
		text(item.id, 'Item ID', MAX_ID)
		if not item.id or item.id in ids:
			raise ValueError('Item IDs must be nonempty and unique: %r' % item.id)
		ids.add(item.id)
		text(item.title, 'Item title', MAX_TITLE)
		if not item.title:
			raise ValueError('Item titles must not be empty.')
		text(item.hint, 'Item hint', MAX_HINT)
		text(item.description, 'Item description', MAX_DESCRIPTION)
		if type(item.enabled) is not bool:
			raise TypeError('Item enabled must be True or False.')
		if not isinstance(item.state, str) or item.state not in known:
			raise ValueError('Unknown state %r for preset %r.' % (item.state, states))
		size += _size(item.id) + _size(item.title) + _size(item.hint) + _size(item.description)
		copies.append(CheckListItem(item.id, item.title, item.state, item.hint,
			item.description, item.enabled))
	if size > MAX_TEXT_BYTES:
		raise ValueError('QuickCheckList text exceeds %d bytes.' % MAX_TEXT_BYTES)
	return Prepared(states, PRESETS[states], tuple(copies), title, summary, status,
		filter == 'fuzzy', alternate)


def next_state(states, start, current, step):
	"""The state `step` places along the item's ring: cycleable states plus its own start state."""
	ring = tuple(state.id for state in states if state.cycle or state.id == start)
	return ring[(ring.index(current) + step) % len(ring)]


def label(states, state_id):
	return next(state.label for state in states if state.id == state_id)


def result(items, current, approval):
	changed = {item.id: current[item.id] for item in items if current[item.id] != item.state}
	return CheckListResult(changed, approval)
