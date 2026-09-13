from fman.impl.theme import Theme
from unittest import TestCase


class StatusBarSelectorTest(TestCase):
	def test_public_toolkit_theme_hooks(self):
		self.assertEqual('#panel', Theme._CSS_TO_QSS['.panel'])
		self.assertEqual('#panel', Theme._CSS_TO_QSS['.bottom-panel'])
		self.assertEqual('#plugin-panel-dock', Theme._CSS_TO_QSS['.plugin-panel-dock'])
		self.assertEqual('#plugin-tool-window', Theme._CSS_TO_QSS['.plugin-tool-window'])
		self.assertIn('QuickList QLineEdit', Theme._CSS_TO_QSS['.quicksearch-query'])
		self.assertIn('QuickList QListView::item', Theme._CSS_TO_QSS['.quicksearch-item'])

	def test_normal_pane_style_includes_labels(self):
		self.assertIn(
			'PaneStatusWidget QLabel',
			Theme._CSS_TO_QSS['.statusbar-pane']
		)
	def test_active_background_only_targets_container(self):
		self.assertEqual(
			'PaneStatusWidget[active="true"]',
			Theme._CSS_TO_QSS['.statusbar-pane[active="true"]']
		)