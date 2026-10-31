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
		self.assertIn('QuickCheckList QLineEdit', Theme._CSS_TO_QSS['.quicksearch-query'])
		self.assertIn('QuickCheckList QListView::item', Theme._CSS_TO_QSS['.quicksearch-item'])

	def test_check_list_colors_parse_and_fall_back_to_defaults(self):
		from fman.impl.util.css import parse_css
		from tempfile import TemporaryDirectory
		from os.path import join
		from unittest.mock import Mock
		base = b'''
			* { font-size: 9pt; }
			.quicksearch-item { padding-top: 1px; padding-left: 4px; padding-right: 4px;
				border-top: 1px solid #4d4d4d; border-bottom: 1px solid #363636; }
			.quicksearch-item-title { font-size: 10pt; color: #c8c8c8; }
			.quicksearch-item-title-highlight { color: white; }
			.quicksearch-item-hint { font-size: 8pt; color: white; }
			.quicksearch-item-description { color: #8f908a; }
		'''
		self.assertTrue(parse_css(base))
		with TemporaryDirectory() as directory:
			default, custom = join(directory, 'default.css'), join(directory, 'custom.css')
			with open(default, 'wb') as f:
				f.write(base)
			with open(custom, 'wb') as f:
				f.write(b'.quickchecklist-state-active { color: #102030; }')
			theme = Theme(Mock(), [])
			theme.load(default)
			colors = theme.get_quicksearch_item_css()['check']
			self.assertEqual(('#75715e', '#f68f33', '#3c3a2d'),
				tuple(colors[key].name() for key in ('state', 'active', 'mark')))
			theme.load(custom)
			self.assertEqual('#102030', theme.get_quicksearch_item_css()['check']['active'].name())

	def test_normal_pane_style_includes_labels(self):
		self.assertIn(
			'PaneStatusWidget QLabel',
			Theme._CSS_TO_QSS['.statusbar-pane']
		)