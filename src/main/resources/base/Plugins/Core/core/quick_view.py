from fman import DirectoryPaneCommand
from fman.impl.plugins.plugin import PluginService
from fman.impl.util.qt.thread import run_in_main_thread


class QuickViewService(PluginService):
	@run_in_main_thread
	def start(self):
		self.window._widget._quick_view_owner = self.owner

	@run_in_main_thread
	def dispose(self):
		window = self.window._widget
		session = window.__dict__.get('_quick_view_session')
		if session is not None:
			session.shutdown()
		loader = window.__dict__.get('_quick_view_loader')
		if loader is not None:
			loader.close()
		window._quick_view_owner = None


@run_in_main_thread
def switch_quick_view(pane, pane_index):
	session = pane.window._widget.__dict__.get('_quick_view_session')
	return session.switch_focus(pane_index) if session is not None else False


class ToggleQuickView(DirectoryPaneCommand):
	aliases = ('Toggle QuickView', 'Preview')

	@run_in_main_thread
	def __call__(self):
		window = self.pane.window._widget
		session = window.__dict__.get('_quick_view_session')
		if session is not None:
			session.close()
			return
		if not self.is_visible():
			return
		owner = window.__dict__.get('_quick_view_owner')
		if owner is None or not owner.active:
			return
		from fman.impl.quick_view import QuickViewSession
		panes = self.pane.window.get_panes()
		source = self.pane._widget
		target = next(pane._widget for pane in panes if pane is not self.pane)
		QuickViewSession(window, source, target, owner)

	def is_visible(self):
		return (len(self.pane.window.get_panes()) == 2)


@run_in_main_thread
def _ready_session(pane):
	session = pane.window._widget.__dict__.get('_quick_view_session')
	if session is not None and session.source is pane._widget and session.overlay.canvas.image is not None:
		return session


class _ImageCommand(DirectoryPaneCommand):
	def is_visible(self):
		return _ready_session(self.pane) is not None

	@run_in_main_thread
	def _act(self, name, value=None):
		session = _ready_session(self.pane)
		if session is not None:
			session.image_action(name, value)


class QuickViewFit(_ImageCommand):
	aliases = ('QuickView: Fit',)
	def __call__(self):
		self._act('fit')


class QuickViewActualSize(_ImageCommand):
	aliases = ('QuickView: 100%',)
	def __call__(self):
		self._act('actual_size')


class QuickViewZoomIn(_ImageCommand):
	aliases = ('QuickView: Zoom in',)
	def __call__(self):
		self._act('zoom_in')


class QuickViewZoomOut(_ImageCommand):
	aliases = ('QuickView: Zoom out',)
	def __call__(self):
		self._act('zoom_out')


class QuickViewPan(_ImageCommand):
	aliases = ('QuickView: Pan',)
	def __call__(self, direction='down', large=False):
		self._act('pan', (direction, large))


class SetQuickViewTableLimit(DirectoryPaneCommand):
	aliases = ('Set QuickView table limit',)

	def __call__(self):
		from fman import QuicksearchItem, show_alert, show_quicksearch, show_status_message
		from fman.impl.quick_view_csv import PRESETS, load_table_preset, notify_table_limit_changed, save_table_preset
		current = load_table_preset()
		options = tuple(('%s MB' % format(size, ','), 'DuckDB memory %d MiB%s' % (memory, ' (current)' if size == current else ''), size)
			for size, memory in PRESETS)
		choice = show_quicksearch(lambda query: (QuicksearchItem(size, title, hint=hint)
			for title, hint, size in options if query.casefold() in title.casefold()),
			item=[size for size, memory in PRESETS].index(current))
		if not choice or choice[1] not in dict(PRESETS):
			return
		try:
			save_table_preset(choice[1])
		except (OSError, ValueError) as error:
			show_alert('Could not save the QuickView table limit: %s' % error)
			return
		notify_table_limit_changed()
		show_status_message('QuickView table limit: %s MB.' % format(choice[1], ','), timeout_secs=3)