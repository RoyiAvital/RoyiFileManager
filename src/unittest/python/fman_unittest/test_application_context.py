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

	def test_startup_uses_product_version_without_changing_plugin_version(self):
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
		self.assertEqual('1.7.5', context.fman_version)
		self.assertEqual('1.7.5', fman_application_context.fman.FMAN_VERSION)

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
				self.assertEqual('1.7.5', context.fman_version)
				self.assertEqual('1.7.5', fman_application_context.fman.FMAN_VERSION)

	@patch.object(fman_application_context, 'PLATFORM', 'Windows')
	@patch.object(fman_application_context, 'makedirs')
	@patch.object(fman_application_context, 'IconProvider')
	@patch.object(fman_application_context, 'QFileIconProvider')
	@patch.object(fman_application_context, 'GnomeFileIconProvider')
	def test_windows_does_not_initialize_gnome_icon_provider(
		self, gnome_provider, windows_provider, icon_provider, makedirs
	):
		context = Mock()
		context._get_local_data_file.return_value = 'icons'

		fman_application_context.DevelopmentApplicationContext.\
			_get_icon_provider(context, Mock())

		gnome_provider.assert_not_called()
		windows_provider.assert_called_once_with()
