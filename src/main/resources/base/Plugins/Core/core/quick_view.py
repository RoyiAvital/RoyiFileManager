from fbs_runtime.platform import is_windows
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
	aliases = ('Toggle QuickView',)

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
		return is_windows() and len(self.pane.window.get_panes()) == 2


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