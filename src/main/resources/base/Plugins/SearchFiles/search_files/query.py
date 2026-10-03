"""Text-only Extended-mode query: whitespace-separated AND terms and quoted phrases."""

MAX_QUERY_CHARACTERS = 4096
MAX_TERMS = 32


def parse_terms(query):
	if len(query) > MAX_QUERY_CHARACTERS:
		raise ValueError('Queries are limited to 4,096 characters.')
	terms, position = [], 0
	while position < len(query):
		character = query[position]
		if character.isspace():
			position += 1
			continue
		if character == '"':
			position += 1
			parts = []
			while True:
				end = query.find('"', position)
				if end < 0:
					raise ValueError('Close the quoted phrase with ".')
				parts.append(query[position:end])
				position = end + 1
				if query[position:position + 1] != '"':
					break
				parts.append('"')
				position += 1
			term = ''.join(parts)
		else:
			end = position
			while end < len(query) and not query[end].isspace() and query[end] != '"':
				end += 1
			term, position = query[position:end], end
		if term:
			terms.append(term.casefold())
	if len(terms) > MAX_TERMS:
		raise ValueError('Queries are limited to 32 terms.')
	return tuple(terms)


def compile_text_filter(query):
	terms = parse_terms(query)
	def predicate(cells):
		folded = tuple(cell.casefold() for cell in cells)
		return all(any(term in cell for cell in folded) for term in terms)
	return predicate
