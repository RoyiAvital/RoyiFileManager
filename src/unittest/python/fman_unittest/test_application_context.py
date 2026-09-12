from unittest import TestCase
from unittest.mock import Mock, patch

from fbs_runtime import application_context
from fman.impl import application_context as fman_application_context


class ApplicationContextTest(TestCase):
	def setUp(self):
		self._application_context = application_context._application_context
		application_context._application_context = None

	def tearDown(self):
		application_context._application_context = self._application_context

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
