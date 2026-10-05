"""Qt-free validation and sort-key preparation for show_quick_list."""

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import islice

from fman.impl.ui import ListItem, MAX_LABEL_LENGTH, validate_metadata
from fman.impl.ui.table_data import text
from fman.impl.util.natural import natural_key


MAX_ITEMS = 10000
MAX_TITLE = 512
MAX_HINT = 2048
MAX_ID = 512


@dataclass(frozen=True)
class QuickListState:
	selected: tuple = ()
	chosen: tuple = ()
	current: str | None = None
	query: str = ''
	sort: tuple | None = None


@dataclass(frozen=True)
class PreparedItems:
	items: tuple
	labels: tuple
	keys: dict


def sort_label(value, name):
	if value is None:
		return None
	text(value, name, MAX_LABEL_LENGTH)
	if not value:
		raise ValueError('%s must not be empty.' % name)
	return value


def requested_sort(value):
	if value is None:
		return None
	if not isinstance(value, (tuple, list)) or len(value) != 2 or type(value[1]) is not bool:
		raise TypeError('sort must be None or (label, ascending).')
	return sort_label(value[0], 'Sort label'), value[1]


def settings_name(value):
	if value is None:
		return None
	text(value, 'settings')
	if not value.endswith('.json') or '/' in value or '\\' in value:
		raise ValueError('Use a plug-in-specific JSON filename, not a path.')
	return value


def _key(value):
	if value is None:
		return None
	return natural_key(value) if isinstance(value, str) else value


def prepare_items(items, title_label=None, hint_label=None):
	if isinstance(items, (str, bytes)) or not isinstance(items, Iterable):
		raise TypeError('items must be an iterable of ListItem.')
	items = tuple(islice(items, MAX_ITEMS + 1))
	if len(items) > MAX_ITEMS:
		raise ValueError('A QuickList holds at most %d items.' % MAX_ITEMS)
	ids = set()
	labels = None
	kinds = {}
	for item in items:
		if not isinstance(item, ListItem):
			raise TypeError('items must contain ListItem records.')
		text(item.id, 'Item ID', MAX_ID)
		if not item.id or item.id in ids:
			raise ValueError('Item IDs must be nonempty and unique: %r' % item.id)
		ids.add(item.id)
		text(item.title, 'Item title', MAX_TITLE)
		text(item.hint, 'Item hint', MAX_HINT)
		item_labels = tuple(entry[0] for entry in item.metadata)
		if labels is None:
			labels = item_labels
		elif item_labels != labels:
			raise ValueError('Every item must list the same metadata labels in the same order.')
		validate_metadata(item.metadata)
		for label, key, display in item.metadata:
			if key is not None and kinds.setdefault(label, isinstance(key, str)) != isinstance(key, str):
				raise TypeError('Metadata %r mixes strings and numbers.' % label)
	labels = labels or ()
	fields = tuple(label for label in (title_label, hint_label) if label is not None) + labels
	if len(set(fields)) != len(fields):
		raise ValueError('Title, hint and metadata labels must be unique.')
	keys = {}
	if title_label is not None:
		keys[title_label] = tuple(natural_key(item.title) for item in items)
	if hint_label is not None:
		keys[hint_label] = tuple(natural_key(item.hint) for item in items)
	for index, label in enumerate(labels):
		keys[label] = tuple(_key(item.metadata[index][1]) for item in items)
	return PreparedItems(items, fields, keys)


def selected_ids(selected, prepared):
	if isinstance(selected, (str, bytes)) or not isinstance(selected, Iterable):
		raise TypeError('selected must be an iterable of item IDs.')
	selected = tuple(selected)
	known = {item.id for item in prepared.items}
	unknown = [value for value in selected if value not in known]
	if unknown:
		raise ValueError('Unknown selected item IDs: %r' % (unknown[:3],))
	return set(selected)


def result_ids(result, known):
	if result is None:
		return None
	if not isinstance(result, tuple) or not all(isinstance(value, str) and value in known for value in result):
		raise ValueError('close(result) takes None or a tuple of current item IDs.')
	return result
