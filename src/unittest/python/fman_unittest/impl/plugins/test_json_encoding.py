import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from fman.impl.plugins.config import load_json, read_json_file
from fman.impl.plugins.plugin import ExternalPlugin
from fman.impl.shortcuts import collect_shortcuts


class JsonEncodingTest(TestCase):
	def test_utf8_and_bom_across_readers(self):
		for encoding in ('utf-8', 'utf-8-sig'):
			with self.subTest(encoding=encoding), TemporaryDirectory() as directory:
				path = Path(directory, 'bindings.json')
				bindings = [{'keys': ['Ctrl+X'], 'command': 'caf\u00e9'}]
				path.write_text(json.dumps(bindings, ensure_ascii=False), encoding=encoding)
				self.assertEqual(bindings, load_json([path]))
				self.assertEqual('caf\u00e9', collect_shortcuts([str(path)])[0][1])
				plugin = Mock()
				plugin._config.locate.return_value = [path]
				component = Mock()
				component.load.return_value = []
				ExternalPlugin._configure_component_from_json(plugin, component, 'bindings.json')
				component.load.assert_called_once_with(bindings)
	def test_locale_fallback_only_for_decoding_failure(self):
		error = UnicodeDecodeError('utf-8', b'\xe9', 0, 1, 'invalid')
		with patch('fman.impl.plugins.config.open', side_effect=[error, StringIO('{"legacy": 1}')]) as opened:
			self.assertEqual({'legacy': 1}, read_json_file('settings'))
			self.assertEqual(2, opened.call_count)
		with patch('fman.impl.plugins.config.open', return_value=StringIO('{bad')) as opened:
			with self.assertRaises(json.JSONDecodeError):
				read_json_file('settings')
			opened.assert_called_once()