from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import json
import sys

from fbs_runtime import application_context
from fbs_runtime.build_settings import get_build_settings
from fman.impl import application_context as fman_application_context


class ApplicationContextTest(TestCase):
	def setUp(self):
		self._application_context = application_context._application_context
		application_context._application_context = None
		get_build_settings.cache_clear()

	def tearDown(self):
		application_context._application_context = self._application_context
		get_build_settings.cache_clear()

	def test_get_application_context_returns_singleton(self):
		class DevelopmentContext:
			pass

		class FrozenContext:
			pass

		first = application_context.get_application_context(
			DevelopmentContext, FrozenContext
		)
		second = application_context.get_application_context(
			DevelopmentContext, FrozenContext
		)

		self.assertIs(first, second)

	def test_startup_uses_product_version(self):
		settings_path = Path(__file__).resolve().parents[4] / \
			'src/build/settings/base.json'
		version = json.loads(settings_path.read_text(encoding='utf-8'))['version']
		context = fman_application_context.DevelopmentApplicationContext()
		context.mother_fs = Mock()
		context.plugin_error_handler = Mock()
		context._get_local_data_file = Mock(return_value='Session.json')
		with patch.object(fman_application_context, 'Settings', return_value={}):
			manager = context.session_manager
		window = Mock()
		manager._show_startup_messages(window)
		window.show_status_message.assert_called_once_with(
			'v%s ready.' % version, timeout_secs=5
		)
		self.assertEqual(version, context.app_version)
		self.assertEqual(version, fman_application_context.fman.APP_VERSION)

	def test_frozen_startup_uses_cached_bundled_settings(self):
		with TemporaryDirectory() as bundle_dir:
			settings_path = Path(bundle_dir) / 'resources/build-settings/base.json'
			settings_path.parent.mkdir(parents=True)
			settings_path.write_text(
				json.dumps({'app_name': 'RfmRenameProbe', 'version': '9.8.7'}), encoding='utf-8'
			)
			with patch.object(sys, 'frozen', True, create=True), \
					patch.object(sys, '_MEIPASS', bundle_dir, create=True), \
					patch.object(fman_application_context, 'Settings', return_value={}):
				context = fman_application_context.FrozenApplicationContext()
				context.mother_fs = Mock()
				context.plugin_error_handler = Mock()
				context._get_local_data_file = Mock(return_value='Session.json')
				manager = context.session_manager
				window = Mock()
				manager._show_startup_messages(window)
				window.show_status_message.assert_called_once_with(
					'v9.8.7 ready.', timeout_secs=5
				)
				settings_path.unlink()
				self.assertEqual({'app_name': 'RfmRenameProbe', 'version': '9.8.7'},
					context.build_settings)
				self.assertEqual('9.8.7', context.app_version)

	@patch.object(fman_application_context, 'makedirs')
	@patch.object(fman_application_context, 'IconProvider')
	@patch.object(fman_application_context, 'QFileIconProvider')
	def test_windows_icon_provider_uses_portable_cache(
		self, windows_provider, icon_provider, makedirs
	):
		context = Mock()
		context._get_local_data_file.return_value = 'icons'
		filesystem = Mock()
		fman_application_context.DevelopmentApplicationContext.\
			_get_icon_provider(context, filesystem)
		context._get_local_data_file.assert_called_once_with('Cache', 'Icons')
		makedirs.assert_called_once_with('icons', exist_ok=True)
		windows_provider.assert_called_once_with()
		icon_provider.assert_called_once_with(windows_provider.return_value, filesystem, 'icons')


class NativeWindowsCleanupTest(TestCase):
	def test_source_workflows_with_isolated_settings(self):
		import os
		import subprocess
		script = '''
import os
import sys
from pathlib import Path
from time import monotonic
from unittest.mock import Mock, patch
from fman import CANCEL, YES, load_json
from fman.impl.application_context import get_application_context
from fman.url import as_url
from PyQt5.QtCore import QEvent, QEventLoop, QTimer, Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtTest import QTest

root = Path(os.environ['ROYIFILEMANAGER_USER_SETTINGS']).resolve().parent
fixture = root / 'fixture'
fixture.mkdir()
(fixture / 'sample.txt').write_text('sample', encoding='utf-8')
sys.argv = [sys.argv[0], str(fixture), str(fixture)]
context = get_application_context()
application = context.app
errors = Mock()
context.plugin_error_handler.report = errors

def until(predicate):
	deadline = monotonic() + 10
	loop = QEventLoop()
	timer = QTimer()
	def check():
		if predicate() or errors.called or monotonic() >= deadline:
			loop.quit()
	timer.timeout.connect(check)
	timer.start(5)
	if not predicate():
		loop.exec_()
	timer.stop()
	assert not errors.called, errors.call_args_list
	assert predicate(), 'Native source workflow did not settle'

def step_shown(tour, index):
	step = tour._steps[index]
	return tour._curr_step_index == index and tour._curr_step is step and step._screen is not None and step._screen.isVisible()

try:
	context._load_plugins()
	context.session_manager.show_main_window(context.window)
	until(lambda: context.tour_controller._tour is not None)
	tour = context.tour_controller._tour
	assert context.session_manager.is_first_run
	assert tour._curr_step_index == 0 and tour._curr_step._screen.isVisible()
	pane = context.window.get_panes()[0]
	until(lambda: pane.get_path() == as_url(fixture) and pane._widget._model.rowCount() == 1)
	tour.reject()
	with patch('fman.impl.usage_helper.show_alert', return_value=CANCEL) as alert, patch.object(pane, '_broadcast') as broadcast:
		context.controller.on_location_bar_clicked(pane._widget)
		alert.assert_called_once()
		broadcast.assert_not_called()
		context.controller.on_location_bar_clicked(pane._widget)
		assert alert.call_count == 1
		broadcast.assert_called_once_with('on_location_bar_clicked')

	from core import commands
	def press(key, modifiers=Qt.NoModifier):
		assert context.controller.handle_shortcut(pane._widget, QKeyEvent(QEvent.KeyPress, key, modifiers))
	def settled(location):
		model = pane._widget._model.sourceModel()
		return pane.get_path() == location and not model._scanning and not model._dirty and model._committed_revision == model._revision

	tour = context.tutorial_factory(pane)
	context.tour_controller.start(tour, 1)
	with patch('fman.impl.onboarding.tutorial.QFileDialog.getExistingDirectory', return_value=str(fixture)), patch.object(tour, '_get_src_url', return_value=as_url(fixture)):
		tour._pick_folder()
	assert tour._curr_step_index == 3
	tour._time_taken = 60
	tour.start(4)
	shown_steps = []
	def dismiss_goto(dialog):
		def dismiss():
			shown_steps.append(tour._curr_step_index)
			dialog.reject()
		dialog.shown.connect(lambda: QTimer.singleShot(0, dismiss))
	context.main_window.before_dialog.connect(dismiss_goto)
	try:
		press(Qt.Key_P, Qt.ControlModifier)
		until(lambda: step_shown(tour, 6))
		assert shown_steps == [5]
	finally:
		context.main_window.before_dialog.disconnect(dismiss_goto)
	tour.start(8)
	with patch.object(commands, 'open_native_file_manager') as explorer:
		press(Qt.Key_F10)
		until(lambda: step_shown(tour, 9))
		explorer.assert_called_once_with(str(fixture))
	tour.reject()
	guide = context.cleanupguide_factory(pane)
	context.tour_controller.start(guide)
	guide._next_step()
	guide._arrived_in_folder()
	assert guide._curr_step_index == 2 and guide._curr_step._screen.isVisible()
	guide.complete()

	handler = context.nonexistent_shortcut_handler
	with patch('fman.impl.nonexistent_shortcut_handler.show_alert', return_value=YES):
		handler._offer_to_customize_keybindings('', 'Left', 'go_up')
		handler._offer_to_customize_keybindings('', 'Right', 'open')
	bindings = load_json('Key Bindings.json')
	assert any(item['keys'] == ['Left'] and item['command'] == 'go_up' for item in bindings)
	assert any(item['keys'] == ['Right'] and item['command'] == 'open' for item in bindings)
	settings_files = list((root / 'UserSettings' / 'Plugins' / 'User' / 'Settings').glob('Key Bindings*.json'))
	assert settings_files
	press(Qt.Key_Left)
	until(lambda: settled(as_url(root)))
	pane.place_cursor_at(as_url(fixture))
	press(Qt.Key_Right)
	until(lambda: settled(as_url(fixture)))
	pane.place_cursor_at(as_url(fixture / 'sample.txt'))
	with patch.object(commands, '_open_files') as open_files:
		press(Qt.Key_Right)
		until(lambda: open_files.called)
		open_files.assert_called_once_with([as_url(fixture / 'sample.txt')], pane)
	from fman.impl.widgets import FilterBar
	bar = pane._widget.findChild(FilterBar)
	bar._input.setText('sam')
	bar.show()
	bar._input.setFocus()
	bar._input.setCursorPosition(0)
	with patch.object(commands, '_open_files') as open_files:
		QTest.keyClick(bar._input, Qt.Key_Right)
		application.processEvents()
		assert bar._input.cursorPosition() == 1
		open_files.assert_not_called()
	bar.close()
	from core.fs.local.windows.drives import DrivesFileSystem
	expected_drive = DrivesFileSystem()._get_drive_label('C:')
	with patch.object(DrivesFileSystem, '_get_drives', return_value=['C:']):
		press(Qt.Key_F1, Qt.AltModifier)
		until(lambda: settled('drives://') and pane._widget._model.rowCount() == 2)
		model = pane._widget._model
		assert [model.index(index, 0).data() for index in range(2)] == [expected_drive, 'Network...']
		pane.set_path(as_url(fixture))
		until(lambda: settled(as_url(fixture)))
	with patch.object(commands, 'show_alert') as alert:
		commands.ZenOfFman(context.window)()
		assert 'Updates should be transparent and continuous' not in alert.call_args.args[0]

	manual = root / 'UserSettings' / 'Plugins' / 'Third-party' / 'ManualProbe'
	package = manual / 'manual_cleanup_probe'
	package.mkdir(parents=True)
	package.joinpath('__init__.py').write_text(
		'from fman import ApplicationCommand, show_status_message\\n'
		'class ManualCleanupProbe(ApplicationCommand):\\n'
		'    def __call__(self):\\n'
		'        show_status_message("Manual probe loaded")\\n', encoding='utf-8')
	with patch.object(commands, 'show_status_message'):
		commands.ReloadPlugins(context.window)()
	registered = context.plugin_support.get_application_commands()
	assert 'manual_cleanup_probe' in registered
	assert 'install_plugin' not in registered
	context.plugin_support.run_application_command('manual_cleanup_probe', {})
	until(lambda: context.main_window._status_bar_text.text() == 'Manual probe loaded')
	listing = commands.ListPlugins(pane)
	items = listing._get_matching_plugins('ManualProbe')
	assert len(items) == 1 and items[0].value == str(manual) and not items[0].hint
	assert not (manual / 'Plugin.json').exists()
	with patch.object(commands, 'show_quicksearch', return_value=('', str(manual))):
		listing()
		until(lambda: pane.get_path() == as_url(manual))
		pane.set_path(as_url(fixture))
		until(lambda: pane.get_path() == as_url(fixture))
		with patch.object(commands, 'show_alert'):
			commands.RemovePlugin(context.window)()
	assert not manual.exists()
	assert 'manual_cleanup_probe' not in context.plugin_support.get_application_commands()
	assert not errors.called, errors.call_args_list
finally:
	context.main_window.close()
	application.processEvents()
'''
		with TemporaryDirectory(prefix='windows-cleanup-') as temporary:
			environment = dict(os.environ, QT_QPA_PLATFORM='windows',
				ROYIFILEMANAGER_USER_SETTINGS=str(Path(temporary, 'UserSettings')))
			result = subprocess.run([sys.executable, '-X', 'faulthandler', '-c', script],
				env=environment, capture_output=True, text=True, timeout=60)
		self.assertEqual(0, result.returncode, result.stdout + result.stderr)
