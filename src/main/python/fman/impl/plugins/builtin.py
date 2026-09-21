from fman import ApplicationCommand, DirectoryPaneCommand
from fman.fs import FileSystem, Column
from fman.impl.plugins.plugin import Plugin
from fman.impl.status_bar import next_status_bar_mode, \
	validate_status_bar_settings
from fman import show_status_message
from fman.impl.util import filenotfounderror
from fman.impl.util.qt.thread import run_in_main_thread
from PyQt5.QtCore import Qt

class BuiltinPlugin(Plugin):
	def __init__(
		self, tour_controller, tutorial_factory, cleanupguide_factory, config,
		*super_args
	):
		super().__init__(*super_args)
		self._config = config
		self._status_settings = None

		# We need to define the command classes here so we get access to the
		# scoped variables tour_controller, *_factory. Creating a factory via
		# lambda: ... would not work because fman's current implementation of
		# commands requires them to be actual classes, not lambdas.

		class Tutorial(TourCommand):
			def __init__(self, pane):
				super().__init__(pane, tour_controller, tutorial_factory)

		class CleanupGuide(TourCommand):
			def __init__(self, pane):
				super().__init__(pane, tour_controller, cleanupguide_factory)

		plugin = self
		class ToggleExtendedStatusBar(ApplicationCommand):
			aliases = ('Toggle extended status bar',)
			@run_in_main_thread
			def __call__(self):
				plugin.toggle_extended_status_bar()

		self._register_directory_pane_command(Tutorial)
		self._register_directory_pane_command(CleanupGuide)
		self._register_application_command(ToggleFullscreen)
		self._register_application_command(ToggleExtendedStatusBar)
		self._register_file_system(NullFileSystem)
		self._register_column(NullColumn)
	@property
	def name(self):
		return 'Builtin'
	def initialize_status_bar(self):
		settings = self._config.load_json('Status Bar.json', default={})
		self._status_settings = validate_status_bar_settings(settings)
		self._window.set_extended_status_bar(self._status_settings)
	def toggle_extended_status_bar(self):
		if self._status_settings is None:
			self.initialize_status_bar()
		self._status_settings['mode'] = next_status_bar_mode(
			self._status_settings['mode']
		)
		self._config.save_json('Status Bar.json', self._status_settings)
		self._window.set_extended_status_bar(self._status_settings)
		mode_names = {
			'disabled': 'Disabled', 'single': 'Active pane', 'dual': 'Per pane'
		}
		show_status_message(
			'Extended status bar: ' + mode_names[self._status_settings['mode']],
			timeout_secs=2
		)

class TourCommand(DirectoryPaneCommand):
	def __init__(self, pane, controller, tour_factory):
		super().__init__(pane)
		self._controller = controller
		self._tour_factory = tour_factory
	def __call__(self, step=0):
		self._controller.start(self._tour_factory(self.pane), step)

class ToggleFullscreen(ApplicationCommand):
	@run_in_main_thread
	def __call__(self):
		w = self.window._widget
		w.setWindowState(w.windowState() ^ Qt.WindowFullScreen)

class NullFileSystem(FileSystem):

	scheme = 'null://'

	def get_default_columns(self, path):
		return NullColumn.get_qualified_name(),
	def iterdir(self, path):
		return []
	def scan(self, path, check_canceled):
		from fman.listing import Listing
		check_canceled()
		self.is_dir(path)
		return Listing.create(self.scheme + path, ())
	def is_dir(self, existing_path):
		if not existing_path:
			return True
		raise filenotfounderror(self.scheme + existing_path)
	def exists(self, path):
		return not path

class NullColumn(Column):

	display_name = 'null'
	def text(self, listing, index):
		return ''
	def keys(self, listing, ascending):
		return (0,) * len(listing.names)

	def get_str(self, url):
		return ''
	def get_sort_value(self, url, is_ascending):
		return None