import heapq
import re
import unicodedata
from collections import namedtuple

from search_file_fuzzy.query import parse


SearchEntry = namedtuple(
	'SearchEntry', 'url name relative_path size_bytes modified_ns',
	defaults=(None, None)
)

_SEPARATORS = re.compile(r'[\W_]+')
_OPERATORS = re.compile(r"['^$!|\\\t]")


def _literal(value):
	return unicodedata.normalize('NFKC', value).casefold()


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
		self._literal_paths = [
			_literal(entry.relative_path.replace('/', '\\'))
			for entry in self._entries
		] if mode == 'fuzzy' else []

	def __call__(self, query):
		if self._mode == 'fuzzy' and _OPERATORS.search(query):
			return self._extended(_prepare(parse(query)))
		query = normalize(query)
		if not query:
			return self._entries[:self._max_results]
		if self._mode == 'regular':
			return self._regular(query)
		return self._fuzzy(query)

	def matches(self, query):
		if self._mode == 'regular':
			return [(entry, []) for entry in self(query)]
		groups = _prepare(parse(query)) if _OPERATORS.search(query) else None
		entries = self._extended(groups) if groups is not None else self(query)
		return [
			(entry, self._highlights(entry, query, groups)) for entry in entries
		]

	def _extended(self, groups):
		if not groups:
			return self._entries[:self._max_results]
		ranked = any(
			term.kind == 'fuzzy' and not term.negate
			for group in groups for term, predicate, score_text in group
		)
		result = []
		for index, path in enumerate(self._literal_paths):
			selected = _select(groups, path)
			if selected is None:
				continue
			entry = self._entries[index]
			if not ranked:
				result.append(entry)
				if len(result) == self._max_results:
					break
				continue
			name, relative_path = self._normalized[index]
			score = 0
			for term, text in selected:
				if term.kind == 'fuzzy':
					if text:
						score += max(
							_score(text, name, filename=True),
							_score(text, relative_path, filename=False)
						)
			result.append((score, -index, entry))
		if not ranked:
			return result
		return [entry for _, _, entry in heapq.nlargest(self._max_results, result)]

	def _highlights(self, entry, query, groups):
		title = entry.relative_path.replace('/', '\\')
		if groups is not None:
			text, mapping = _mapped_normalize(title, fuzzy=False)
			selected = _select(groups, text) or []
			positions = []
			for term, score_text in selected:
				positions.extend(_term_positions(term, text))
		else:
			query = normalize(query)
			if not query:
				return []
			name = normalize(entry.name)
			path = normalize(entry.relative_path)
			if _score(query, name, True) >= _score(query, path, False):
				offset = len(title[:-len(entry.name)].encode('utf-16-le')) // 2
				text, mapping = _mapped_normalize(entry.name, offset=offset)
			else:
				text, mapping = _mapped_normalize(title)
			start = text.find(query)
			if start >= 0:
				positions = range(start, start + len(query))
			else:
				positions = [
					position for token in query.split()
					for position in (_find_subsequence(token, text) or [])
				]
		return sorted({unit for position in positions for unit in mapping[position]})

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


def _prepare(groups):
	return tuple(tuple(
		(term._replace(text=_literal(term.text)), _predicate(term),
		 normalize(term.text) if term.kind == 'fuzzy' else '')
		for term in group
	) for group in groups)


def _predicate(term):
	text = _literal(term.text)
	if term.kind == 'fuzzy':
		return lambda candidate: _find_subsequence(text, candidate) is not None
	if term.kind == 'exact':
		return lambda candidate: text in candidate
	return _term_regex(term.kind, text).search


def _term_regex(kind, text):
	pattern = re.escape(text)
	if kind == 'boundary':
		pattern = r'(?<![^\W_])' + pattern + r'(?![^\W_])'
	if kind in ('prefix', 'equal'):
		pattern = (r'^' if text[0].isspace() else r'^\s*') + pattern
	if kind in ('suffix', 'equal'):
		pattern += (r'\Z' if text[-1].isspace() else r'\s*\Z')
	return re.compile(pattern)


def _select(groups, candidate):
	selected = []
	for group in groups:
		passed = False
		for term, predicate, score_text in group:
			matched = bool(predicate(candidate))
			if term.negate:
				passed |= not matched
			elif matched:
				selected.append((term, score_text))
				passed = True
				break
		if not passed:
			return None
	return selected


def _term_positions(term, candidate):
	if term.kind == 'fuzzy':
		return _find_subsequence(term.text, candidate) or []
	if term.kind == 'exact':
		start = candidate.find(term.text)
	else:
		match = _term_regex(term.kind, term.text).search(candidate)
		start = candidate.find(term.text, match.start()) if match else -1
	return range(start, start + len(term.text)) if start >= 0 else []


def _mapped_normalize(value, fuzzy=True, offset=0):
	characters = []
	mapping = []
	for character in value:
		units = tuple(range(offset, offset + (2 if ord(character) > 0xffff else 1)))
		offset += len(units)
		normalized = unicodedata.normalize('NFKC', character)
		characters.extend(normalized)
		mapping.extend([units] * len(normalized))
	if ''.join(characters) != unicodedata.normalize('NFKC', value):
		characters, mapping = _mapped_composition(value, offset - len(value.encode('utf-16-le')) // 2)
	result = []
	positions = []
	previous = ''
	for character, units in zip(characters, mapping):
		if fuzzy and previous and character.isupper() and \
				(previous.islower() or previous.isdigit()):
			result.append(' ')
			positions.append(())
		for folded in character.casefold():
			if fuzzy and _SEPARATORS.fullmatch(folded):
				folded = ' '
			if fuzzy and folded == ' ' and result and result[-1] == ' ':
				positions[-1] += units
			else:
				result.append(folded)
				positions.append(units)
		previous = character
	if fuzzy:
		start = 1 if result and result[0] == ' ' else 0
		end = len(result) - (1 if result and result[-1] == ' ' else 0)
		return ''.join(result[start:end]), positions[start:end]
	return ''.join(result), positions


def _mapped_composition(value, offset):
	text = ''
	mapping = []
	for index, character in enumerate(value):
		normalized = unicodedata.normalize('NFKC', value[:index + 1])
		common = 0
		for old, new in zip(text, normalized):
			if old != new:
				break
			common += 1
		width = 2 if ord(character) > 0xffff else 1
		units = tuple(sorted({unit for span in mapping[common:] for unit in span}))
		units += tuple(range(offset, offset + width))
		offset += width
		mapping[common:] = [units] * (len(normalized) - common)
		text = normalized
	return text, mapping


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