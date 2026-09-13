from fman.impl.theme import Theme
from unittest import TestCase


class StatusBarSelectorTest(TestCase):
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