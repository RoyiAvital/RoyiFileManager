from core.about import AboutWindow, ZEN
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QLabel
from unittest import TestCase

import json
from pathlib import Path


class AboutWindowTest(TestCase):
	ROOT = Path(__file__).resolve().parents[8]

	def setUp(self):
		self.app = QApplication.instance() or QApplication([])
		self.metadata = json.loads((self.ROOT / 'src/build/settings/AppMeta.json').read_text(encoding='utf-8'))
		self.window = AboutWindow('RoyiFileManager', self.metadata, str(self.ROOT / 'src/main/icons/Icon.ico'))
		self.addCleanup(self.window.deleteLater)

	def texts(self):
		return [label.text() for label in self.window.findChildren(QLabel)]

	def test_shows_metadata_icon_and_zen_without_buttons(self):
		texts = '\n'.join(self.texts())
		for value in (self.metadata['version'], self.metadata['description'], 'The Zen of RoyiFileManager',
				'href="%s"' % self.metadata['project_link'], 'href="%s"' % self.metadata['documentation_link']):
			self.assertIn(value, texts)
		for line in ZEN:
			self.assertIn(line, texts)
		self.assertTrue(any(not label.pixmap().isNull() for label in self.window.findChildren(QLabel)
			if label.pixmap() is not None))
		self.assertTrue(self.window.windowFlags() & Qt.FramelessWindowHint)
		from PyQt5.QtWidgets import QAbstractButton
		self.assertEqual([], self.window.findChildren(QAbstractButton))

	def test_metadata_is_escaped(self):
		window = AboutWindow('App', {'version': '1', 'project_link': 'https://x.test/?a=<b>&c'}, '')
		self.addCleanup(window.deleteLater)
		links = next(label.text() for label in window.findChildren(QLabel) if 'href' in label.text())
		self.assertIn('href="https://x.test/?a=&lt;b&gt;&amp;c"', links)

	def test_escape_and_enter_close(self):
		for key in (Qt.Key_Escape, Qt.Key_Return):
			with self.subTest(key=key):
				window = AboutWindow('App', self.metadata, '')
				window.show_centered()
				QTest.keyClick(window, key)
				self.assertFalse(window.isVisible())
