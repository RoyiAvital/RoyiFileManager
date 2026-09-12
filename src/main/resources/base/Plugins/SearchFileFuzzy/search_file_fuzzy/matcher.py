import heapq
import re
import unicodedata
from collections import namedtuple


SearchEntry = namedtuple('SearchEntry', 'url name relative_path')

_SEPARATORS = re.compile(r'[\W_]+')


def normalize(value):
	value = unicodedata.normalize('NFKC', value)
	value = _split_camel_case(value)
	return _SEPARATORS.sub(' ', value.casefold()).strip()


def _split_camel_case(value):
	result = []
	previous = ''
	for character in value:
		if previous and character.isupper() and \
				(previous.islower() or previous.isdigit()):
			result.append(' ')
		result.append(character)
		previous = character
	return ''.join(result)


class Matcher:
	def __init__(self, entries, mode='fuzzy', max_results=100):
		if mode not in ('fuzzy', 'regular'):
			raise ValueError('Search mode must be "fuzzy" or "regular".')
		self._entries = list(entries)
		self._mode = mode
		self._max_results = max(1, int(max_results))
		self._normalized = [
			(normalize(entry.name), normalize(entry.relative_path))
			for entry in self._entries
		]

	def __call__(self, query):
		query = normalize(query)
		if not query:
			return self._entries[:self._max_results]
		if self._mode == 'regular':
			return self._regular(query)
		return self._fuzzy(query)

	def _regular(self, query):
		result = []
		for entry, (_, relative_path) in zip(self._entries, self._normalized):
			if query in relative_path:
				result.append(entry)
				if len(result) == self._max_results:
					break
		return result

	def _fuzzy(self, query):
		scored = []
		for index, (name, relative_path) in enumerate(self._normalized):
			score = max(
				_score(query, name, filename=True),
				_score(query, relative_path, filename=False)
			)
			if score != float('-inf'):
				scored.append((score, -index, self._entries[index]))
		return [
			entry for _, _, entry in heapq.nlargest(self._max_results, scored)
		]


def _score(query, candidate, filename):
	if query == candidate:
		return 10_000
	bonus = 500 if filename else 0
	if candidate.startswith(query):
		return 9_000 + bonus - len(candidate)
	position = candidate.find(query)
	if position >= 0:
		return 8_000 + bonus - position - len(candidate) * 0.01

	total = 0
	for token in query.split():
		positions = _find_subsequence(token, candidate)
		if positions is None:
			return float('-inf')
		span = positions[-1] - positions[0] + 1
		boundaries = sum(
			position == 0 or candidate[position - 1] == ' '
			for position in positions
		)
		total += boundaries * 30 - span * 3 - positions[0]
	return 5_000 + bonus + total - len(candidate) * 0.01


def _find_subsequence(query, candidate):
	positions = []
	cursor = 0
	for character in query:
		cursor = candidate.find(character, cursor)
		if cursor < 0:
			return None
		positions.append(cursor)
		cursor += 1
	return positions