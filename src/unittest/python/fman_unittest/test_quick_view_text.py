from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from fman.impl.quick_view_images import ImageRequest, load_preview
from fman.impl.quick_view_text import (
	TextContent, FORMAT_LIMIT, READ_LIMIT, PROBE_LIMIT, LANGUAGES, FILENAMES,
	convert_text, decode_text, is_binary, language_for, load_text
)


class TextConversionTest(TestCase):
	def content(self, text, path='sample.py', **kwargs):
		return TextContent(text, path, 'utf-8', (), len(text.encode('utf-8')), **kwargs)

	def test_plain_source_and_limits_never_import_markdown(self):
		import builtins
		original = builtins.__import__
		def restricted(name, *args, **kwargs):
			if name in ('markdown', 'pygments'):
				raise AssertionError('Unexpected formatter import')
			return original(name, *args, **kwargs)
		with patch('builtins.__import__', side_effect=restricted):
			for content, mode in ((self.content('# <tag> *literal*', 'plain.txt'), 'rendered'),
				(self.content('# Source', 'sample.md'), 'source'),
				(replace(self.content('large'), byte_count=FORMAT_LIMIT + 1), 'rendered'),
				(self.content('prefix', truncated=True), 'rendered')):
				result = convert_text(content, mode)
				self.assertEqual('', result.html)
				self.assertEqual(content.text, result.content.text)

	def test_code_markdown_and_literal_html(self):
		result = convert_text(self.content('def example():\n    return "``` <tag> & \U0001f600"'))
		self.assertIn('style="color:', result.html)
		self.assertIn('&lt;tag&gt;', result.html)
		self.assertIn('```', result.html)
		self.assertNotIn('background: #272822', result.html)
		markdown = '# Title\n\n| Name | Value |\n| --- | --- |\n| one | two |\n\n<div>literal</div>\n\n```python\ndef example():\n    pass\n```'
		result = convert_text(self.content(markdown, 'sample.md'))
		self.assertIn('<h1>Title</h1>', result.html)
		self.assertIn('<table>', result.html)
		self.assertIn('&lt;div&gt;', result.html)
		self.assertNotIn('<div>literal</div>', result.html)

	def test_languages_unknown_fences_and_converter_isolation(self):
		for path in ['sample' + suffix for suffix in LANGUAGES] + list(FILENAMES):
			with self.subTest(path=path):
				result = convert_text(self.content('value = 42\n', path))
				self.assertTrue(result.html)
				self.assertNotEqual('Formatting unavailable', result.message)
		unknown = convert_text(self.content('```unknown_language_123\ntext <tag>\n```', 'sample.md'))
		self.assertIn('&lt;tag&gt;', unknown.html)
		convert_text(self.content('[ref]: https://example.invalid\n\n[ref]', 'one.md'))
		self.assertNotIn('href=', convert_text(self.content('[ref]', 'two.md')).html)

	def test_conversion_failure_output_limit_and_cancellation(self):
		with patch('markdown.Markdown', side_effect=RuntimeError('bad converter')):
			self.assertEqual('Formatting unavailable', convert_text(self.content('hello')).message)
		with patch('fman.impl.quick_view_text.HTML_LIMIT', 10):
			self.assertEqual('', convert_text(self.content('hello')).html)
		self.assertIsNone(convert_text(self.content('hello'), canceled=lambda: True))
		with patch('fman.impl.quick_view_text.importlib.import_module', side_effect=ImportError('missing')):
			self.assertEqual('Formatting unavailable', convert_text(self.content('hello')).message)
		result = convert_text(self.content('prefix', warning='Encoding warning', truncated=True))
		self.assertIn('Encoding warning', result.message)
		self.assertIn('truncated', result.message)

	def test_decoding_and_binary_threshold(self):
		for encoding in ('utf-8-sig', 'utf-16', 'utf-32'):
			self.assertEqual('Hello \U0001f600', decode_text('Hello \U0001f600'.encode(encoding), True)[0])
		self.assertEqual('hello', decode_text(b'hello\xe2\x82', False)[0])
		with patch('fman.impl.quick_view_text.locale.getencoding', return_value='cp1252'):
			self.assertEqual('caf\u00e9', decode_text(b'caf\xe9', True)[0])
		self.assertTrue(is_binary('a\0b'))
		self.assertFalse(is_binary('a' * 99 + '\x01'))
		self.assertTrue(is_binary('a' * 98 + '\x01\x02'))
		self.assertFalse(is_binary('text\t\r\n\f'))

	def test_damaged_utf8_preserves_valid_unicode(self):
		accented = 'caf\u00e9 r\u00e9sum\u00e9'
		for source, damage, tail, complete in (
			(accented, b'\xff', b'', True),
			(accented, b'\xff' * 3, b'', True),
			(accented * 100, b'\xff' * 4, b'', True),
			(accented + '\ufffd' * 4, b'\xff', b'', True),
			(accented, b'\xff', b'\xe2\x82', False)
		):
			with self.subTest(source=source[:30], damage=damage, complete=complete), \
					patch('fman.impl.quick_view_text.locale.getencoding') as ansi:
				text, encoding, warning = decode_text(source.encode('utf-8') + damage + tail, complete)
				self.assertEqual(source + '\ufffd' * len(damage), text)
				self.assertEqual('utf-8', encoding)
				self.assertIn('replacement characters', warning)
				ansi.assert_not_called()

	def test_ansi_retry_remains_for_ambiguous_or_heavily_damaged_text(self):
		for data in (b'caf\xe9', 'caf\u00e9'.encode('utf-8') + b'\xff' * 4):
			with self.subTest(data=data), \
					patch('fman.impl.quick_view_text.os.name', 'nt'), \
					patch('fman.impl.quick_view_text.locale.getencoding', return_value='cp1252'):
				self.assertEqual((data.decode('cp1252'), 'cp1252', 'Windows ANSI: cp1252'),
					decode_text(data, True))


class TextLoadingTest(TestCase):
	def setUp(self):
		self.folder = TemporaryDirectory()
		self.addCleanup(self.folder.cleanup)

	def request(self, name, data):
		path = Path(self.folder.name, name)
		path.write_bytes(data)
		return ImageRequest(1, 'file://' + path.as_posix())

	def load(self, request):
		return load_preview(request, lambda: False, lambda url: url)

	def test_plain_markdown_code_and_binary_dispatch(self):
		for name, data, kind in (('readme', b'Hello', 'text'), ('sample.md', b'# Heading', 'text'),
			('script.py', b'pass', 'text'), ('binary', b'\0' * 100, 'unsupported'),
			('script.ts', b'const value: number = 42;', 'text'), ('binary.ts', b'\0' * 100, 'unsupported'),
			('broken.png', b'not an image', 'error')):
			with self.subTest(name=name):
				self.assertEqual(kind, self.load(self.request(name, data)).kind)

	def test_julia_files_are_syntax_highlighted(self):
		source = 'function greet(name)\n    return "Hello, $name"\nend\n'
		for suffix in ('.jl', '.JL'):
			with self.subTest(suffix=suffix):
				result = self.load(self.request('script' + suffix, source.encode('utf-8')))
				self.assertEqual('text', result.kind)
				self.assertEqual(source, result.content.text)
				self.assertEqual('code', result.mode)
				self.assertEqual('', result.message)
				self.assertRegex(result.html, r'<span style="[^"]*color:[^"]*">function</span>')

	def test_matlab_files_are_syntax_highlighted(self):
		source = 'function value = square(input)\n    value = input.^2;\nend\n'
		for suffix in ('.m', '.M'):
			with self.subTest(suffix=suffix):
				result = self.load(self.request('script' + suffix, source.encode('utf-8')))
				self.assertEqual('matlab', language_for(result.content.path))
				self.assertEqual('text', result.kind)
				self.assertEqual(source, result.content.text)
				self.assertEqual('code', result.mode)
				self.assertEqual('', result.message)
				self.assertRegex(result.html, r'<span style="[^"]*color:[^"]*">function</span>')

	def test_excluded_binaries_do_not_open_and_probe_does_not_read_tail(self):
		request = self.request('binary.exe', b'a' * 100)
		with patch('builtins.open', side_effect=AssertionError('Unexpected read')):
			self.assertEqual('unsupported', self.load(request).kind)
		request = self.request('unknown', b'\0' * PROBE_LIMIT + b'x' * 10000)
		import builtins
		original = builtins.open
		reads = []
		def tracked(*args, **kwargs):
			stream = original(*args, **kwargs)
			read = stream.read
			def limited(size=-1):
				reads.append(size)
				return read(size)
			stream.read = limited
			return stream
		with patch('builtins.open', side_effect=tracked):
			self.assertEqual('unsupported', self.load(request).kind)
		self.assertEqual([PROBE_LIMIT], reads)

	def test_read_and_format_caps(self):
		result = self.load(self.request('large.py', b'x' * (READ_LIMIT + 100)))
		self.assertEqual(READ_LIMIT, len(result.content.text))
		self.assertTrue(result.content.truncated)
		self.assertEqual('', result.html)
		self.assertIn('truncated', result.message)
		result = self.load(self.request('medium.md', b'x' * (FORMAT_LIMIT + 1)))
		self.assertIn('512 KiB', result.message)
		self.assertEqual('', result.html)

	def test_cached_mode_conversion_and_cancellation_do_no_io(self):
		result = self.load(self.request('readme.md', b'# Heading'))
		request = ImageRequest(2, 'file://removed', mode='source', content=result.content)
		with patch('builtins.open', side_effect=AssertionError('Unexpected I/O')):
			self.assertEqual('# Heading', self.load(request).content.text)
			self.assertIsNone(load_text(request, lambda: True))

	def test_changed_file_during_conversion_is_rejected(self):
		request = self.request('changing.py', b'pass')
		def change(content, *args):
			Path(content.path).write_bytes(b'changed contents')
			return convert_text(content, *args)
		with patch('fman.impl.quick_view_text.convert_text', side_effect=change):
			result = self.load(request)
		self.assertEqual('error', result.kind)
		self.assertIn('changed', result.message)

	def test_unknown_image_and_broken_recognized_content_do_not_become_text(self):
		from PyQt5.QtGui import QImage
		path = Path(self.folder.name, 'image.unknown')
		image = QImage(3, 2, QImage.Format_RGB32)
		image.fill(0xff123456)
		self.assertTrue(image.save(str(path), 'PNG'))
		request = ImageRequest(1, 'file://' + path.as_posix())
		result = self.load(request)
		self.assertEqual('image', result.kind)
		self.assertEqual((3, 2), (result.image.width(), result.image.height()))
		path.write_bytes(path.read_bytes()[:24])
		self.assertEqual('error', self.load(request).kind)