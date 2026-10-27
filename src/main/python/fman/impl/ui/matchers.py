from os.path import basename
import os


def path_starts_with(path, query):
	query = query.rstrip(os.sep)
	if path.lower().startswith(query.lower()):
		return list(range(len(query)))


def basename_starts_with(path, query):
	name = basename(path.lower())
	if name.startswith(query.lower()):
		offset = len(path) - len(name)
		return list(range(offset, offset + len(query)))


def contains_chars(text, query):
	contiguous = contains_substring(text, query)
	if contiguous is not None:
		return contiguous
	indices = []
	position = 0
	for char in query:
		position = text.find(char, position)
		if position < 0:
			return None
		indices.append(position)
		position += 1
	return indices


def contains_substring(text, query):
	start = text.find(query)
	if start >= 0:
		return list(range(start, start + len(query)))


def contains_chars_after_separator(separator):
	def match(text, query):
		positions = []
		skip_to_next_part = False
		for index, char in enumerate(text):
			if skip_to_next_part:
				if char == separator:
					skip_to_next_part = False
				continue
			if not query:
				break
			if char == query[0]:
				positions.append(index)
				query = query[1:]
			else:
				skip_to_next_part = char != separator
		if not query:
			return positions
	return match


def display_positions(text, lowered, positions):
	"""Map positions in lowered == text.lower() to Qt (UTF-16) positions in text."""
	if positions is None or text.isascii() or len(lowered) == len(text) and \
			len(text.encode('utf-16-le', 'surrogatepass')) == 2 * len(text):
		return positions
	units, unit = [], 0
	for char in text:
		width = 2 if ord(char) > 0xffff else 1
		units.extend([range(unit, unit + width)] * len(char.lower()))
		unit += width
	return sorted({value for position in positions for value in units[position]})