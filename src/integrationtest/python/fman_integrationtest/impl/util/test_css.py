from fman.impl.theme import Theme, ThemeError
from fman.impl.util.css import parse_css, Rule, Declaration, CSSParseError, CSSEngine
from hashlib import sha256
from pathlib import Path
from PyQt5.QtGui import QColor
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

import json
import os
import subprocess
import sys

class ParseCSSTest(TestCase):
	def test_parse_css(self):
		self.maxDiff = None
		self.assertEqual([
			Rule(['*'], [Declaration('font-size', '1pt')]),
			Rule(['.a'], [Declaration('font-size', '2pt')]),
			Rule(['.a', '.b'], [Declaration('font-size', '3pt')]),
		], parse_css(_TEST_CSS))
	def test_legacy_selector_and_value_text(self):
		cases = (
			(b'.a,.b { color: red; }', ['.a,.b'], 'color', 'red'),
			(b'.a ,  .b { color: red; }', ['.a ', ' .b'], 'color', 'red'),
			(b".pane[active='true'] { font-family: 'Open Sans'; }",
			 [".pane[active='true']"], 'font-family', "'Open Sans'"),
			(b'.a { COLOR: r/**/ed !IMPORTANT; }', ['.a'], 'color', 'red'),
			(b'.a { border: 1px  solid #262626; }',
			 ['.a'], 'border', '1px  solid #262626'),
		)
		for source, selectors, property_name, value in cases:
			with self.subTest(source=source):
				self.assertEqual(
					[Rule(selectors, [Declaration(property_name, value)])],
					parse_css(source)
				)
	def test_legacy_byte_decoding(self):
		expected = [Rule(['.a'], [Declaration('font-family', '"caf\u00e9"')])]
		for source in (
			b'.a { font-family: "caf\xc3\xa9"; }',
			b'\xef\xbb\xbf.a { font-family: "caf\xc3\xa9"; }',
			b'@charset "utf-8"; .a { font-family: "caf\xc3\xa9"; }',
			b'\xef\xbb\xbf@charset "utf-8"; .a { font-family: "caf\xc3\xa9"; }',
			b'@charset "iso-8859-1"; .a { font-family: "caf\xe9"; }',
			b'.a { font-family: "caf\xe9"; }',
		):
			with self.subTest(source=source):
				self.assertEqual(expected, parse_css(source))
	def test_legacy_eof_recovery(self):
		self.assertEqual(
			[Rule(['.a'], [Declaration('color', 'red')])],
			parse_css(b'.a { color: red;')
		)
	def test_empty_stylesheets(self):
		for source in (b'', b' \r\n\t', b'/* comment */', b'/* unfinished',
				b'@charset "utf-8";'):
			with self.subTest(source=source):
				self.assertEqual([], parse_css(source))
	def test_wide_encodings(self):
		expected = [Rule(['.a'], [Declaration('font-family', '"caf\u00e9"')])]
		for encoding in ('utf-16', 'utf-16-be', 'utf-16-le',
				'utf-32', 'utf-32-be', 'utf-32-le'):
			with self.subTest(encoding=encoding):
				source = '@charset "%s"; .a { font-family: "caf\u00e9"; }' % encoding
				self.assertEqual(expected, parse_css(source.encode(encoding)))
		for encoding in ('utf-16', 'utf-32'):
			with self.subTest(bom_only=encoding):
				self.assertEqual(expected, parse_css(
					'.a { font-family: "caf\u00e9"; }'.encode(encoding)
				))
	def test_declared_encoding_fallback(self):
		for encoding in ('unknown-encoding', 'utf-8'):
			with self.subTest(encoding=encoding):
				source = ('@charset "%s"; .a { font-family: "caf' % encoding).encode() + \
					b'\xe9"; }'
				self.assertEqual(
					[Rule(['.a'], [Declaration('font-family', '"caf\u00e9"')])],
					parse_css(source)
				)
		with self.assertRaises(CSSParseError):
			parse_css('@charset "latin-1"; .a { color: red; }'.encode('utf-16'))
	def test_nested_source_text_and_comment_removal(self):
		source = b".a { value: calc(1/**/px + fn('x/*not a comment*/y')); }"
		self.assertEqual(
			[Rule(['.a'], [Declaration('value', "calc(1px + fn('x/*not a comment*/y'))")])],
			parse_css(source)
		)
		self.assertEqual(1, CSSEngine(parse_css(
			b'.a { padding: 1/**/px; }'
		)).parse_px('.a', 'padding'))
	def test_escaped_text_and_crlf_preserved(self):
		self.assertEqual(
			[Rule(['.\\61 '], [Declaration('color', 'r\\65 d\r\n  blue')])],
			parse_css(b'.\\61 { co\\6c or: r\\65 d\r\n  blue; }')
		)
	def test_quoted_delimiters_and_url_text(self):
		self.assertEqual(
			[Rule(['.a'], [Declaration('value', "'a,;{}b' url('x;y.png')")])],
			parse_css(b".a { value: 'a,;{}b' url('x;y.png'); }")
		)
	def test_nested_token_errors(self):
		cases = (
			b'.a] { color: red; }',
			b'.a { color: red]; }',
			b'.a { color: rgb(1, 2, ]); }',
			b'.a { value: [one )]; }',
			b'.a { background: url(foo bar); }',
			b'.a { font-family: "bad\nvalue"; }',
		)
		for source in cases:
			with self.subTest(source=source):
				with self.assertRaises(CSSParseError) as caught:
					parse_css(source)
				self.assertIsInstance(caught.exception, ValueError)
				self.assertGreaterEqual(caught.exception.line, 1)
				self.assertGreaterEqual(caught.exception.column, 1)
				self.assertTrue(caught.exception.reason)
	def test_error_positions(self):
		for source, line, column in (
			(b'.a { color red; }', 1, 12),
			(b'.a {\r\n color: red];\r\n}', 2, 12),
			(b'.a {\r color: red];\r}', 2, 12),
			(b'.a {\f color: red];\f}', 2, 12),
		):
			with self.subTest(source=source):
				with self.assertRaises(CSSParseError) as caught:
					parse_css(source)
				self.assertEqual((line, column),
					(caught.exception.line, caught.exception.column))
	def test_unsupported_rules_and_empty_declarations(self):
		for source in (
			b'@media screen { .a { color: red; } }', b'@import "other.css";',
			b'.a { @unknown foo; }', b'.a {} @charset "utf-8";',
			b'{ color: red; }', b'.a { color:; }', b'.a; { color: red; }',
		):
			with self.subTest(source=source):
				with self.assertRaises(CSSParseError):
					parse_css(source)
	def test_theme_error_preserves_previous_appearance(self):
		app = Mock()
		theme = Theme(app, [])
		theme.load(str(_CORE / 'Theme.css'))
		theme.enable_updates()
		before = theme.get_quicksearch_item_css()
		app.reset_mock()
		with TemporaryDirectory() as temporary:
			path = Path(temporary) / 'Broken.css'
			path.write_bytes(b'.a {\r\n color: red];\r\n}')
			with self.assertRaises(ThemeError) as caught:
				theme.load(str(path))
			self.assertTrue(caught.exception.description.startswith(
				'CSS Parse error in file %s at line 2, column 12: ' % path
			))
		self.assertEqual(before, theme.get_quicksearch_item_css())
		app.set_style_sheet.assert_not_called()
	def test_warning_free_import_without_legacy_parser(self):
		with TemporaryDirectory() as temporary:
			environment = dict(os.environ,
				PYTHONPYCACHEPREFIX=temporary, PYTHONDONTWRITEBYTECODE='1')
			result = subprocess.run([
				sys.executable, '-W', 'error::SyntaxWarning', '-c',
				'import sys; import fman.impl.util.css, fman.impl.theme; '
				'assert "tinycss" not in sys.modules'
			], env=environment, capture_output=True, text=True, timeout=60)
		self.assertEqual(0, result.returncode, result.stdout + result.stderr)
	def test_shipped_rule_snapshots(self):
		for filename, expected in _RULE_SNAPSHOTS.items():
			path = _PLUGIN_THEME if filename == 'Simple Plugin' else \
				_CORE / filename
			with self.subTest(filename=filename):
				self.assertEqual(expected, _fingerprint(parse_css(path.read_bytes())))
	def test_generated_theme_snapshots(self):
		for platform, expected in _THEME_SNAPSHOTS.items():
			with self.subTest(platform=platform):
				app = Mock()
				theme = Theme(app, [])
				theme.load(str(_CORE / 'Theme.css'))
				if platform == 'Plugin':
					theme.load(str(_PLUGIN_THEME))
				elif platform != 'Base':
					theme.load(str(_CORE / ('Theme (%s).css' % platform)))
				theme.enable_updates()
				self.assertEqual(expected, _fingerprint({
					'qss': app.set_style_sheet.call_args.args[0],
					'quicksearch': theme.get_quicksearch_item_css()
				}))

def _fingerprint(value):
	serialized = json.dumps(
		value, sort_keys=True, ensure_ascii=True,
		default=lambda color: color.name(QColor.HexArgb)
	)
	return sha256(serialized.encode('utf-8')).hexdigest()

_CORE = Path(__file__).resolve().parents[5] / 'main/resources/base/Plugins/Core'
_PLUGIN_THEME = Path(__file__).resolve().parents[4] / \
	'resources/Simple Plugin/Theme.css'
_RULE_SNAPSHOTS = {
	'Theme.css': 'e6e74ecd7c8d6b5e2089864c2cc59125cc602d289f85f0e5dfcb57065a5d8521',
	'Theme (Windows).css': '6bae24eaf5a5982ce36fbed375dda00e13738ac0969e68f42da4920de89b5725',
	'Theme (Mac).css': 'f893ae25cd26a916651f59a7d0d6ecef01799981b4ee1a5d043da51ce18d373b',
	'Theme (Linux).css': '466b16a936e1ceabdcadc117e05006315fc6ec541cee625821b36ae5942bd96c',
	'Simple Plugin': '4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945',
}
_THEME_SNAPSHOTS = {
	'Base': '488379aa59811f1aa3f95fb9d28a7cebe2e1346ca03eda60c5090e6c2ed81ac2',
	'Windows': '1b260fd1c52215b30b464f5ec3c5ea94f7959d2043c1de4885bdf3bc6c729c0e',
	'Mac': '1f69d09b83b4466e3a8283c21eb149a1436773b19f9cadad423d2421f327ec87',
	'Linux': 'e24aa941a1a687b40e301c4ad6faf3d3d474d92d4ef081a8bd25eb370e72b521',
	'Plugin': '488379aa59811f1aa3f95fb9d28a7cebe2e1346ca03eda60c5090e6c2ed81ac2',
}

_TEST_CSS = \
b"""* {
	font-size: 1pt;
}

.a {
	font-size: 2pt;
}

.a, .b {
	font-size: 3pt;
}"""