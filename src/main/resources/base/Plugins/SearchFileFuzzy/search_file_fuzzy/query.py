import re
from collections import namedtuple


Term = namedtuple('Term', 'kind text negate')


def parse(query):
	query = query.lstrip(' ')
	while query.endswith(' ') and not query.endswith('\\ '):
		query = query[:-1]
	groups = []
	alternatives = []
	new_group = False
	after_bar = False
	for token in re.split(' +', query.replace('\\ ', '\t')):
		text = token.replace('\t', ' ')
		if alternatives and not after_bar and text == '|':
			new_group = False
			after_bar = True
			continue
		after_bar = False
		kind = 'fuzzy'
		negate = text.startswith('!')
		if negate:
			kind = 'exact'
			text = text[1:]
		if text != '$' and text.endswith('$'):
			kind = 'suffix'
			text = text[:-1]
		if len(text) > 2 and text.startswith("'") and text.endswith("'"):
			kind = 'boundary'
			text = text[1:-1]
		elif text.startswith("'"):
			kind = 'fuzzy' if negate else 'exact'
			text = text[1:]
		elif text.startswith('^'):
			kind = 'equal' if kind == 'suffix' else 'prefix'
			text = text[1:]
		if text:
			if new_group:
				groups.append(tuple(alternatives))
				alternatives = []
			alternatives.append(Term(kind, text, negate))
			new_group = True
	if alternatives:
		groups.append(tuple(alternatives))
	return tuple(groups)