"""Real QuickView controls, correct preview paints and active input responsiveness."""

import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import perf_counter, process_time

from fman_performancetest.filter_find import distribution, memory


def _install_paint_dispatch():
	from fman.impl.view import FileListView
	original_paint = FileListView.paintEvent
	def dispatch_paint(view, event):
		return original_paint(view, event)
	FileListView.paintEvent = dispatch_paint


def child(directory, viewport, navigation_repetitions=5):
	with TemporaryDirectory(prefix='quickview-performance-') as temporary:
		settings = Path(temporary) / 'UserSettings'
		os.environ['ROYIFILEMANAGER_USER_SETTINGS'] = str(settings)
		from fman import DATA_DIRECTORY
		from fman.impl.application_context import get_application_context
		from fman.impl.util.qt.thread import run_in_main_thread
		from fman.url import as_url
		from PyQt5.QtCore import QCoreApplication, QEvent, QObject, QTimer
		if Path(DATA_DIRECTORY).resolve() != settings:
			raise RuntimeError('Settings isolation failed')
		_install_paint_dispatch()
		user = settings / 'Plugins/User/Settings'
		user.mkdir(parents=True)
		(user / 'Panes.json').write_text(json.dumps([{'show_hidden_files': True}] * 2), encoding='utf-8')
		(user / 'QuickView.json').write_text('{"image_mode":"fit"}', encoding='utf-8')
		empty = Path(temporary) / 'empty'
		empty.mkdir()
		context = get_application_context()
		app = context.app
		window = context.main_window
		context.session_manager.is_first_run = False
		sys.argv = [sys.argv[0], str(directory), str(empty)]
		gui = lambda function: run_in_main_thread(function)()
		active = {}
		report = dict(settings_isolated=True, samples=[], errors=[],
			notes='Warm filesystem cache, fresh application process. Production 100 ms debounce included. '
			'Paint means completed Qt paint cycle, not compositor presentation. Pixel validation is untimed.')
		original_hook = sys.excepthook
		def exception(error_type, error, trace):
			report['errors'].append(str(error))
			original_hook(error_type, error, trace)
		sys.excepthook = exception
		probe_type = QEvent.Type(QEvent.registerEventType())
		class Probe(QEvent):
			def __init__(self, token, action=None):
				super().__init__(probe_type)
				self.token, self.action, self.started = token, action, perf_counter()
		def completed(token):
			if not active or token is not active['token'] or active['done'].is_set() or not active['predicate']():
				return
			now = perf_counter()
			active['paint_ms'] = (now - active['start']) * 1000
			active['cpu_ms'] = (process_time() - active['cpu_start']) * 1000
			active['gaps'].append((now - active['tick']) * 1000)
			active['done'].set()
		class Observer(QObject):
			def event(self, event):
				if event.type() == probe_type:
					if active and event.token is active['token'] and not active['done'].is_set():
						active['queue'].append((perf_counter() - event.started) * 1000)
						if event.action:
							active['delivered'] = True
							event.action()
					return True
				return super().event(event)
			def eventFilter(self, watched, event):
				if active and active['delivered'] and not active['done'].is_set() and event.type() == QEvent.Paint and watched is active['surface']() and active['predicate']():
					token = active['token']
					QTimer.singleShot(0, lambda: completed(token))
				return False
		observer = Observer()
		app.installEventFilter(observer)
		def tick():
			if active and not active['done'].is_set():
				now = perf_counter()
				active['gaps'].append((now - active['tick']) * 1000)
				active['tick'] = now
		timer = QTimer()
		timer.setInterval(10)
		timer.timeout.connect(tick)
		timer.start()
		def wait_until(predicate, label):
			done = Event()
			def install():
				poll = QTimer(window)
				poll.setInterval(10)
				def check():
					if predicate():
						poll.stop()
						poll.deleteLater()
						done.set()
				poll.timeout.connect(check)
				poll.start()
				check()
			gui(install)
			if not done.wait(90):
				raise TimeoutError(label)
		def measure(identity, action, predicate, surface):
			started = perf_counter()
			active.update(token=object(), start=started, cpu_start=process_time(), tick=started,
				done=Event(), delivered=False, predicate=predicate, surface=surface, gaps=[], queue=[])
			QCoreApplication.postEvent(observer, Probe(active['token'], action))
			while not active['done'].wait(.01):
				if perf_counter() - started > 90:
					raise TimeoutError(identity)
				QCoreApplication.postEvent(observer, Probe(active['token']))
			result = dict(action_id=identity, input_to_paint_ms=active['paint_ms'], cpu_ms=active['cpu_ms'],
				heartbeat_gap_ms=distribution(active['gaps']), queue_dispatch_ms=distribution(active['queue']),
				heartbeat_samples_ms=active['gaps'], queue_samples_ms=active['queue'], **memory())
			active.clear()
			report['samples'].append(result)
			return result
		def exercise():
			code = 1
			try:
				panes = context.window.get_panes()
				def loaded():
					for pane, location in zip(panes, (directory, empty)):
						listing = pane._widget.get_listing()
						model = pane._widget._model.sourceModel()
						if listing is None or listing.location != as_url(location) or model._scanning or model._committed_revision != model._revision:
							return False
					return len(panes) == 2
				wait_until(loaded, 'Requested pane listings')
				left, right = panes
				gui(lambda: window.resize(*viewport))
				if gui(window.devicePixelRatioF) != 1:
					raise RuntimeError('Unexpected DPI scale')
				report['viewport'] = gui(lambda: [window.width(), window.height()])
				report['listing_entries'] = len(gui(left.get_listing).names)
				if 'fman.impl.quick_view' in sys.modules or getattr(window, '_quick_view_loader', None) is not None:
					raise RuntimeError('Disabled QuickView performed initialization')
				report['disabled_lazy'] = True
				baseline = gui(lambda: (right.get_path(), right.get_file_under_cursor(), right.get_selected_files()))
				def session():
					return getattr(window, '_quick_view_session', None)
				def canvas():
					return session().overlay.canvas if session() is not None else None
				def surface():
					return canvas().viewport() if canvas() is not None else None
				def select(name):
					left.place_cursor_at(as_url(directory / name))
				def ready(name, dimensions, format_):
					return session() is not None and session()._url == as_url(directory / name) and canvas().image is not None and (canvas().image.width(), canvas().image.height()) == dimensions and session().overlay.image_format == format_
				def pixels():
					image = canvas().viewport().grab().toImage()
					color = image.pixelColor(image.width() // 2, image.height() // 2)
					if not (color.green() > 130 and color.red() < 80 and color.blue() < 100):
						raise RuntimeError('Preview pixels do not match the synthetic image')
				def image_case(identity, name, dimensions, format_, action=None):
					result = measure(identity, action or (lambda: select(name)),
						lambda: ready(name, dimensions, format_), surface)
					gui(pixels)
					result['pixels_verified'] = True
				measure('disabled-navigation', lambda: select('preview-small.png'),
					lambda: session() is None and getattr(window, '_quick_view_loader', None) is None and left.get_file_under_cursor() == as_url(directory / 'preview-small.png'),
					lambda: left._widget._file_view.viewport())
				image_case('enable.png', 'preview-small.png', (1280, 960), 'png', lambda: left.run_command('toggle_quick_view'))
				image_case('switch.large-png', 'preview-large.png', (4096, 3072), 'png')
				image_case('switch.jpeg', 'preview-small.jpg', (1280, 960), 'jpeg')
				image_case('switch.bmp', 'preview-small.bmp', (1280, 960), 'bmp')
				for identity, name in (('invalid-image', 'preview-invalid.png'), ('unsupported-file', 'preview-unsupported.txt')):
					measure(identity, lambda name=name: select(name),
						lambda: canvas().image is None and canvas().message.startswith('Unsupported image'), surface)
				image_case('restore.large-png', 'preview-large.png', (4096, 3072), 'png')
				for identity, command, predicate, arguments in (
					('actual-size', 'quick_view_actual_size', lambda: canvas().mode == 'actual_size', {}),
					('zoom-in', 'quick_view_zoom_in', lambda: canvas().scale == 1.25, {}),
					('pan-right', 'quick_view_pan', lambda: canvas().horizontalScrollBar().value() > 0, {'direction': 'right', 'large': True}),
					('fit', 'quick_view_fit', lambda: canvas().mode == 'fit', {})):
					result = measure(identity, lambda command=command, arguments=arguments: left.run_command(command, arguments), predicate, surface)
					gui(pixels)
					result['pixels_verified'] = True
				def rapid():
					sequence = ('preview-small.png', 'preview-large.png', 'preview-small.jpg', 'preview-small.bmp')
					for index, name in enumerate(sequence):
						QTimer.singleShot(index * 30, lambda name=name: select(name))
				image_case('rapid-navigation-final', 'preview-small.bmp', (1280, 960), 'bmp', rapid)
				from fman_performancetest.navigation import measure as measure_navigation
				report['navigation'] = measure_navigation(left._widget._file_view, gui, navigation_repetitions)
				image_case('restore.bmp-after-navigation', 'preview-small.bmp', (1280, 960), 'bmp')
				def close():
					left.run_command('toggle_quick_view')
					right._widget._file_view.viewport().update()
				measure('close', close, lambda: session() is None, lambda: right._widget._file_view.viewport())
				wait_until(lambda: getattr(window, '_quick_view_loader', None) is None, 'Preview worker release')
				report['released_memory'] = memory()
				image_case('reopen.bmp', 'preview-small.bmp', (1280, 960), 'bmp', lambda: left.run_command('toggle_quick_view'))
				def cancel_pending():
					select('preview-large.png')
					close()
				measure('cancel-debounced-preview', cancel_pending, lambda: session() is None, lambda: right._widget._file_view.viewport())
				wait_until(lambda: getattr(window, '_quick_view_loader', None) is None, 'Canceled worker release')
				if baseline != gui(lambda: (right.get_path(), right.get_file_under_cursor(), right.get_selected_files())):
					raise RuntimeError('QuickView changed the target pane state')
				if report['errors']:
					raise RuntimeError('Application exceptions')
				report.update(memory())
				print('QUICKVIEW_RESULT ' + json.dumps(report), flush=True)
				code = 0
			except BaseException:
				import traceback
				traceback.print_exc()
			finally:
				def stop():
					current = getattr(window, '_quick_view_session', None)
					if current is not None:
						current.shutdown()
					for pane in context.window.get_panes():
						pane._widget._model.shutdown()
					app.exit(code)
				gui(stop)
		QTimer.singleShot(0, lambda: Thread(target=exercise, daemon=True).start())
		return context.run()