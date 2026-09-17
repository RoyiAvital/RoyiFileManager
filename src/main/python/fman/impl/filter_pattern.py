from dataclasses import dataclass

import re


MAX_FILTER_LENGTH = 255


@dataclass(frozen=True)
class FilterMatcher:
	segments: tuple[re.Pattern, ...] = ()
	negate: bool = False

	def matches(self, name):
		if len(self.segments) == 1:
			return bool(self.segments[0].search(name)) != self.negate
		position = 0
		for segment in self.segments:
			match = segment.search(name, position)
			if match is None:
				return self.negate
			position = match.end()
		return not self.negate


def compile_filter(text):
	text = text[:MAX_FILTER_LENGTH]
	original = tuple(_tokenize(text))
	tokens = list(original)
	negate = bool(tokens and tokens[0] == ('literal', '!'))
	if negate:
		tokens.pop(0)
	anchored_start = bool(tokens and tokens[0] == ('literal', '^'))
	if anchored_start:
		tokens.pop(0)
	anchored_end = bool(tokens and tokens[-1] == ('literal', '$'))
	if anchored_end:
		tokens.pop()
	if not tokens:
		tokens = original
		negate = anchored_start = anchored_end = False
	leading_star = bool(tokens and tokens[0][0] == 'star')
	trailing_star = bool(tokens and tokens[-1][0] == 'star')
	segments = []
	current = []
	for kind, value in tokens:
		if kind == 'star':
			if current:
				segments.append(''.join(current))
				current = []
		else:
			current.append(value if kind == 'pattern' else re.escape(value))
	if current:
		segments.append(''.join(current))
	if segments:
		if anchored_start and not leading_star:
			segments[0] = r'\A' + segments[0]
		if anchored_end and not trailing_star:
			segments[-1] += r'\Z'
	try:
		return FilterMatcher(tuple(re.compile(segment, re.I) for segment in segments), negate)
	except re.error:
		return FilterMatcher((re.compile(re.escape(text), re.I),))


def _tokenize(text):
	position = 0
	while position < len(text):
		char = text[position]
		if char == '\\':
			position += 1
			if position < len(text):
				yield 'escaped', text[position]
		elif char == '*':
			yield 'star', ''
		elif char == '?':
			yield 'pattern', '.'
		elif char == '[':
			character_class = _read_class(text, position)
			if character_class is not None:
				pattern, position = character_class
				yield 'pattern', pattern
			else:
				yield 'literal', char
		else:
			yield 'literal', char
		position += 1


def _read_class(text, start):
	position = start + 1
	negate = position < len(text) and text[position] == '!'
	position += int(negate)
	members = []
	while position < len(text):
		char = text[position]
		escaped = char == '\\' and position + 1 < len(text)
		if escaped:
			position += 1
			char = text[position]
		elif char == ']' and members:
			body = ''.join(
				'-' if value == '-' and not literal and 0 < index < len(members) - 1
				and members[index - 1][0] != '-' and members[index + 1][0] != '-' else re.escape(value)
				for index, (value, literal) in enumerate(members)
			)
			return '[' + ('^' if negate else '') + body + ']', position
		members.append((char, escaped))
		position += 1
	return None