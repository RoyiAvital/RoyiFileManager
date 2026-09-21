from codecs import BOM_UTF8, BOM_UTF16_BE, BOM_UTF16_LE, BOM_UTF32_BE, BOM_UTF32_LE
from collections import namedtuple
from PyQt5.QtGui import QColor

import re
import tinycss2

Rule = namedtuple('Rule', ('selectors', 'declarations'))
Declaration = namedtuple('Declaration', ('property', 'value'))

class CSSParseError(ValueError):
	def __init__(self, line, column, reason):
		super().__init__('line %d, column %d: %s' % (line, column, reason))
		self.line, self.column, self.reason = line, column, reason

def parse_css(bytes_):
	source = _decode_css(bytes_)
	tokens = tinycss2.parse_component_value_list(source)
	texts = _source_token_texts(source, tokens)
	result = []
	nodes = tinycss2.parse_stylesheet(tokens, skip_comments=True, skip_whitespace=True)
	for index, node in enumerate(nodes):
		_check_parse_error(node)
		if node.type == 'at-rule':
			prelude = [token for token in node.prelude
				if token.type not in ('whitespace', 'comment')]
			if index == 0 and node.lower_at_keyword == 'charset' and \
					node.content is None and len(prelude) == 1 and \
					prelude[0].type == 'string':
				continue
			_raise_css_error(node, 'Unsupported at-rule: @' + node.at_keyword)
		for token in node.prelude:
			if token.type == 'literal' and token.value == ';':
				_raise_css_error(token, 'Unexpected semicolon in selector')
		selector_text = _trimmed_text(node.prelude, texts)
		if not selector_text:
			_raise_css_error(node, 'Expected a selector before the declaration block')
		selectors = selector_text.split(', ')
		declarations = []
		for declaration in tinycss2.parse_declaration_list(
			node.content, skip_comments=True, skip_whitespace=True
		):
			_check_parse_error(declaration)
			if declaration.type == 'at-rule':
				_raise_css_error(
					declaration, 'Unsupported at-rule: @' + declaration.at_keyword
				)
			value = _trimmed_text(declaration.value, texts)
			if not value:
				_raise_css_error(declaration, 'Expected a property value')
			declarations.append(Declaration(declaration.lower_name, value))
		result.append(Rule(selectors, declarations))
	return result

def _decode_css(bytes_):
	bom_encoding = None
	payload = bytes_
	for encoding, marker in (
		('utf-32-be', BOM_UTF32_BE), ('utf-32-le', BOM_UTF32_LE),
		('utf-16-be', BOM_UTF16_BE), ('utf-16-le', BOM_UTF16_LE),
		('utf-8', BOM_UTF8)
	):
		if bytes_.startswith(marker):
			bom_encoding = encoding
			payload = bytes_[len(marker):]
			break
	declared_encoding = None
	for encoding in ('utf-8', 'utf-16-be', 'utf-16-le', 'utf-32-be', 'utf-32-le'):
		prefix = '@charset "'.encode(encoding)
		if not payload.startswith(prefix):
			continue
		end = payload.find('";'.encode(encoding), len(prefix))
		if end != -1:
			declared_encoding = payload[len(prefix):end].decode(encoding, 'replace')
			if declared_encoding.replace('-', '').replace('_', '').lower() in \
					('utf16', 'utf32') and encoding.endswith(('-be', '-le')):
				declared_encoding += encoding[-3:]
		break
	preferred = declared_encoding if declared_encoding is not None else bom_encoding
	for index, encoding in enumerate((preferred, 'utf-8')):
		if encoding is None:
			continue
		try:
			text = bytes_.decode(encoding).removeprefix('\ufeff')
		except (UnicodeError, LookupError):
			continue
		if index == 0 and declared_encoding is not None and \
				not text.startswith('@charset "'):
			continue
		return text
	return bytes_.decode('latin-1')

def _source_token_texts(source, tokens):
	line_starts = [0] + [match.end() for match in re.finditer(r'\r\n|[\r\n\f]', source)]
	texts = {}
	def position(token):
		return line_starts[token.source_line - 1] + token.source_column - 1
	def collect(items, end):
		for index, token in enumerate(items):
			_check_parse_error(token)
			start = position(token)
			stop = position(items[index + 1]) if index + 1 < len(items) else end
			children = getattr(token, 'content', getattr(token, 'arguments', None))
			if children is not None:
				closing = {'{} block': '}', '[] block': ']',
					'() block': ')', 'function': ')'}[token.type]
				content_end = stop - 1 if source[stop - 1:stop] == closing else stop
				collect(children, content_end)
				if children:
					texts[id(token)] = source[start:position(children[0])] + \
						''.join(texts[id(child)] for child in children) + \
						source[content_end:stop]
				else:
					texts[id(token)] = source[start:stop]
			else:
				texts[id(token)] = '' if token.type == 'comment' else source[start:stop]
	collect(tokens, len(source))
	return texts

def _trimmed_text(tokens, texts):
	tokens = [token for token in tokens if token.type != 'comment']
	start, end = 0, len(tokens)
	while start < end and tokens[start].type == 'whitespace':
		start += 1
	while end > start and tokens[end - 1].type == 'whitespace':
		end -= 1
	return ''.join(texts[id(token)] for token in tokens[start:end])

def _check_parse_error(node):
	if node.type == 'error':
		_raise_css_error(node, node.message)

def _raise_css_error(node, reason):
	raise CSSParseError(node.source_line, node.source_column, reason)

class CSSEngine:
	def __init__(self, parsed_css):
		self._rules = parsed_css
	def parse_border_width(self, selector, declaration):
		value = self._query(selector, declaration)
		width = value.split(' ')[0]
		error_message = \
			'Invalid value for %s %s: %r. Should be of the form ' \
			'"123px solid #ff0000".' % (selector, declaration, value)
		if not width.endswith('px'):
			raise ValueError(error_message)
		try:
			return int(width[:-2])
		except ValueError:
			raise ValueError(error_message) from None
	def parse_pts(self, selector, declaration):
		value = self._query(selector, declaration)
		error_message = \
			'Invalid pt value for %s %s: %r' % (selector, declaration, value)
		if not value.endswith('pt'):
			raise ValueError(error_message)
		try:
			return int(value[:-2])
		except ValueError:
			raise ValueError(error_message) from None
	def parse_color(self, selector, declaration):
		value = self._query(selector, declaration)
		return QColor(value)
	def parse_px(self, selector, declaration):
		value = self._query(selector, declaration)
		error_message = \
			'Invalid px value for %s %s: %r' % (selector, declaration, value)
		if not value.endswith('px'):
			raise ValueError(error_message)
		try:
			return int(value[:-2])
		except ValueError:
			raise ValueError(error_message) from None
	def _query(self, selector, declaration):
		declarations = self._get_declarations(selector)
		try:
			return declarations[declaration]
		except KeyError:
			raise ValueError(
				'Could not find %s for %s' % (declaration, selector)
			)
	def _get_declarations(self, selector):
		result = {}
		for rule in self._rules:
			for sel in rule.selectors:
				if sel == '*' or sel == selector:
					for declaration in rule.declarations:
						result[declaration.property] = declaration.value
		return result