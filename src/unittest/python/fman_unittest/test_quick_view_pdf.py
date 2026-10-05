from _quick_view_pdf_worker import (
	FrameDecoder, MAX_HEADER, PdfError, encode_frame, valid_geometry, valid_raster
)
from build import _pdf_smoke_fixture as pdf_bytes
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import os
import struct
import subprocess
import sys


def worker_command(executable=None):
	return [executable or sys.executable, '-B', str(Path(__file__).resolve().parents[4] /
		'src/main/python/fman/main.py'), '--quick-view-pdf-worker']


def command(kind, operation=1, **values):
	return encode_frame(dict(type=kind, epoch=1, generation=1, operation=operation, revision=0, **values))


class PdfProtocolTest(TestCase):
	def test_missing_renderer_and_changed_source(self):
		from _quick_view_pdf_worker import Document
		from types import SimpleNamespace
		from unittest.mock import patch
		with TemporaryDirectory() as directory:
			path = Path(directory) / 'report.pdf'
			path.write_bytes(pdf_bytes())
			with patch.dict(sys.modules, {'pypdfium2': None}), self.assertRaisesRegex(PdfError, 'unavailable'):
				Document().open(str(path))
			info = path.stat()
			changed = SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino,
				st_size=info.st_size + 1, st_mtime_ns=info.st_mtime_ns)
			with patch('_quick_view_pdf_worker.os.fstat', return_value=changed), self.assertRaisesRegex(PdfError, 'changed'):
				Document().open(str(path))

	def test_pdf_dispatch_is_lazy_and_never_text(self):
		from fman.impl.quick_view_images import ImageRequest, load_preview
		from unittest.mock import Mock, patch
		with patch('fman.impl.quick_view_text.load_text', side_effect=AssertionError('PDF reached text')):
			result = load_preview(ImageRequest(1, 'file://C:/report.PDF'), lambda: False, lambda url: url)
			self.assertEqual('pdf', result.kind)
			self.assertEqual('C:\\report.PDF', result.path)
			resolve = Mock(side_effect=AssertionError('Unexpected resolution'))
			self.assertEqual('error', load_preview(ImageRequest(1, 'zip://archive/report.pdf'), lambda: False, resolve).kind)
			self.assertIsNone(load_preview(ImageRequest(1, 'file://C:/report.pdf'), lambda: True, resolve))
			resolve.assert_not_called()

	def test_fit_and_raster_geometry(self):
		from fman.impl.quick_view_pdf_view import page_layout, raster_size
		sizes = ((200, 400), (400, 200))
		rects, scales, width, height = page_layout(sizes, 424, 624, 'fit_page', 1)
		self.assertEqual([1.5, 1], scales)
		self.assertEqual(16, rects[1].top() - rects[0].bottom())
		self.assertEqual([2, 1], page_layout(sizes, 424, 624, 'fit_width', 1)[1])
		self.assertEqual([4 / 3, 4 / 3], page_layout(sizes, 424, 624, 'manual', 1)[1])
		for geometry in ((1, 10000000, 2), (10000000, 1, 2), (10000, 10000, 3), (600, 800, 1.5)):
			self.assertTrue(valid_raster(*raster_size(*geometry)))

	def test_split_and_coalesced_frames(self):
		decoder = FrameDecoder()
		data = encode_frame({'type': 'page'}, b'pixels') + encode_frame({'type': 'ready'})
		frames = []
		for index in range(0, len(data), 3):
			frames.extend(decoder.feed(data[index:index + 3]))
		decoder.finish()
		self.assertEqual(['page', 'ready'], [header['type'] for header, payload in frames])
		self.assertEqual(b'pixels', frames[0][1])

	def test_bad_lengths_headers_and_truncation(self):
		for data in (struct.pack('<I', MAX_HEADER + 1), struct.pack('<I', 0),
			struct.pack('<I', 2) + b'{}', struct.pack('<I', 1) + b'!',
			struct.pack('<I', 2000) + b'[' * 1000 + b']' * 1000):
			with self.subTest(data=data), self.assertRaises(PdfError):
				FrameDecoder().feed(data)
		decoder = FrameDecoder()
		decoder.feed(encode_frame({'type': 'page'}, b'abc')[:-1])
		with self.assertRaises(PdfError):
			decoder.finish()

	def test_limits(self):
		self.assertTrue(valid_raster(2000, 4000))
		for size in ((0, 1), (8193, 1), (2001, 4000), (True, 1), (1.0, 1)):
			self.assertFalse(valid_raster(*size))
		for size in ((0, 1), (float('nan'), 1), (float('inf'), 1), (True, 1)):
			self.assertFalse(valid_geometry(size))


class PdfWorkerTest(TestCase):
	def test_packaging_collects_backend_binary_and_notices(self):
		import ast
		from importlib.metadata import distribution
		from PyInstaller.utils.hooks import collect_dynamic_libs
		tree = ast.parse((Path(__file__).resolve().parents[4] / 'application.spec').read_text(encoding='utf-8'))
		calls = {(node.func.id, node.args[0].value) for node in ast.walk(tree)
			if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.args and
			isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)}
		self.assertIn(('collect_all', 'pypdfium2_raw'), calls)
		self.assertIn(('copy_metadata', 'pypdfium2'), calls)
		self.assertTrue(any(Path(source).name.lower() == 'pdfium.dll' and Path(source).is_file()
			for source, destination in collect_dynamic_libs('pypdfium2_raw')))
		package = distribution('pypdfium2')
		for name in ('pdfium.txt', 'Apache-2.0.txt', 'BSD-3-Clause.txt'):
			self.assertTrue(any(path.name == name and Path(package.locate_file(path)).is_file() for path in package.files))

	def run_worker(self, payload, executable=None):
		result = subprocess.run(worker_command(executable), input=payload, capture_output=True, timeout=30)
		self.assertEqual(0, result.returncode, result.stderr.decode('utf-8', 'replace'))
		decoder = FrameDecoder()
		frames = decoder.feed(result.stdout)
		decoder.finish()
		return frames

	def test_render_colored_pages_and_source_release(self):
		with TemporaryDirectory() as directory:
			path = Path(directory) / 'report.pdf'
			path.write_bytes(pdf_bytes())
			frames = self.run_worker(command('open', path=str(path)) +
				command('render', 2, page=0, width=200, height=200) +
				command('render', 3, page=1, width=300, height=150) + command('close', 4))
			self.assertEqual(['ready', 'document', 'page', 'page'], [header['type'] for header, pixels in frames])
			self.assertEqual([[200, 200], [300, 150]], frames[1][0]['sizes'])
			for (header, pixels), expected in zip(frames[2:], (b'\x00\x00\xff\xff', b'\x00\xff\x00\xff')):
				offset = header['stride'] * (header['height'] // 2) + (header['width'] // 2) * 4
				self.assertEqual(expected, pixels[offset:offset + 4])
				self.assertEqual(header['stride'] * header['height'], len(pixels))
			path.rename(path.with_suffix('.moved')).unlink()

	def test_rotated_page(self):
		with TemporaryDirectory() as directory:
			path = Path(directory) / 'rotated.pdf'
			path.write_bytes(pdf_bytes(((300, 150),), rotation=90))
			frames = self.run_worker(command('open', path=str(path)) + command('render', 2, page=0, width=150, height=300))
			self.assertEqual([[150, 300]], frames[1][0]['sizes'])
			self.assertEqual('page', frames[2][0]['type'])

	def test_bad_document_returns_error(self):
		with TemporaryDirectory() as directory:
			path = Path(directory) / 'bad.pdf'
			path.write_bytes(b'not a PDF')
			frames = self.run_worker(command('open', path=str(path)))
			self.assertEqual('error', frames[1][0]['type'])
			self.assertTrue(frames[1][0]['message'])

	def test_worker_imports_no_qt_or_optional_imaging(self):
		code = "import _quick_view_pdf_worker, sys; assert not any(name.startswith(('PyQt5', 'PIL', 'numpy', 'pypdfium2')) for name in sys.modules)"
		result = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, timeout=10)
		self.assertEqual(0, result.returncode, result.stderr)

	def test_normal_quickview_does_not_import_pdf_modules(self):
		code = "import fman.impl.quick_view, sys; assert not any(name in sys.modules for name in ('_quick_view_pdf_worker', 'fman.impl.quick_view_pdf', 'fman.impl.quick_view_pdf_view', 'pypdfium2'))"
		result = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, timeout=10)
		self.assertEqual(0, result.returncode, result.stderr)

	def test_windowed_interpreter_binary_pipes(self):
		if sys.platform != 'win32':
			self.skipTest('Windows pipe bootstrap')
		executable = Path(sys.executable).with_name('pythonw.exe')
		self.assertTrue(executable.is_file())
		frames = self.run_worker(command('close'), str(executable))
		self.assertEqual('ready', frames[0][0]['type'])


class PdfControllerTest(TestCase):
	def run_qt(self, body):
		code = '''
from fman.impl.quick_view_pdf import PdfController
from fman_unittest.test_quick_view_pdf import pdf_bytes
from pathlib import Path
from tempfile import TemporaryDirectory
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QEventLoop, QTimer
import sys
app = QApplication([])
def until(predicate, timeout=5000):
	loop = QEventLoop()
	timer = QTimer()
	timer.timeout.connect(lambda: loop.quit() if predicate() else None)
	timer.start(5)
	deadline = QTimer()
	deadline.setSingleShot(True)
	deadline.timeout.connect(loop.quit)
	deadline.start(timeout)
	loop.exec_()
	timer.stop()
	deadline.stop()
	assert predicate(), 'Timed out waiting for test condition'
''' + body
		result = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True,
			env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts')), timeout=30)
		self.assertEqual(0, result.returncode, result.stderr.decode('utf-8', 'replace'))
		if result.stdout:
			print(result.stdout.decode('utf-8', 'replace').strip())

	def test_real_render_release_stale_revision_and_teardown(self):
		self.run_qt('''
with TemporaryDirectory() as directory:
	path = Path(directory) / 'report.pdf'
	path.write_bytes(pdf_bytes())
	controller = PdfController()
	documents, pages, errors = [], [], []
	controller.document_ready.connect(lambda *args: documents.append(args))
	controller.page_ready.connect(lambda *args: pages.append(args))
	controller.failed.connect(lambda *args: errors.append(args))
	controller.open(1, str(path))
	until(lambda: documents or errors)
	assert not errors, errors
	path.rename(path.with_suffix('.renamed')).unlink()
	controller.request_pages(1, 1, ((0, 200, 200),))
	controller.request_pages(1, 2, ((1, 300, 150),))
	until(lambda: pages or errors)
	assert not errors, errors
	assert len(pages) == 1 and pages[0][1] == 2 and pages[0][2]['page'] == 1
	assert not controller.deadline.isActive()
	assert not any(name.startswith('pypdfium2') for name in sys.modules)
	controller.invalidate()
	until(lambda: controller.process is None)
	assert controller.job is None and not controller.deadline.isActive()
	controller.shutdown()
''')

	def test_scrolling_preserves_inflight_raster(self):
		self.run_qt('''
from fman.impl.quick_view_pdf_view import PdfPreview
from PyQt5.QtWidgets import QWidget
source = QWidget()
view = PdfPreview(source)
view.resize(620, 740)
view.show()
app.processEvents()
canvas = view.canvas
controller = PdfController()
requests, errors = [], []
canvas.requested.connect(lambda revision, targets: controller.request_pages(1, revision, targets))
controller.page_ready.connect(lambda generation, revision, request, result: canvas.set_page(revision, request, result))
controller.failed.connect(lambda *args: errors.append(args))
def loaded(generation, sizes, fingerprint):
	canvas.set_document(sizes)
	request = dict(controller._active)
	assert request['type'] == 'render'
	requests.append(request)
	canvas.verticalScrollBar().setValue(40)
	assert canvas.revision == request['revision']
	assert controller._revision == request['revision']
controller.document_ready.connect(loaded)
with TemporaryDirectory() as directory:
	path = Path(directory) / 'report.pdf'
	path.write_bytes(pdf_bytes(((200, 400), (200, 400))))
	try:
		controller.open(1, str(path))
		until(lambda: bool(canvas.cache) or errors)
		assert not errors, errors
		request = requests[0]
		assert (request['page'], request['width'], request['height']) in canvas.cache
		revision = canvas.revision
		canvas.zoom_by(1)
		assert canvas.revision > revision
		canvas.clear()
		pixels = bytes(request['width'] * request['height'] * 4)
		canvas.set_page(revision, request, ({'width': request['width'], 'height': request['height'], 'stride': request['width'] * 4}, pixels))
		assert not canvas.cache
	finally:
		controller.invalidate()
		until(lambda: controller.process is None)
		controller.shutdown()
		view.close()
''')

	def test_late_callbacks_after_process_retirement(self):
		self.run_qt('''
from PyQt5.QtCore import QProcess
controller = PdfController()
errors, drained = [], []
controller.failed.connect(lambda *args: errors.append(args))
controller._generation = 7
controller.process = QProcess(controller)
controller._retiring = True
QTimer.singleShot(0, controller._read_error)
QTimer.singleShot(0, controller._started)
QTimer.singleShot(0, controller._read)
QTimer.singleShot(0, lambda: drained.append(True))
controller._finished()
assert controller.process is None
until(lambda: bool(drained))
assert not errors
assert controller.process is None and controller.job is None
assert not controller.deadline.isActive() and not controller.drain.isActive()
controller.shutdown()
''')

	def test_startup_hang_and_crash_stay_local(self):
		self.run_qt('''
import fman.impl.quick_view_pdf as module
module.START_TIMEOUT = 100
for body in ('from threading import Event; Event().wait()', 'import os; os._exit(3)'):
	controller = PdfController(command=[sys.executable, '-B', '-c', body])
	errors = []
	controller.failed.connect(lambda *args: errors.append(args))
	controller.open(7, 'unused.pdf')
	until(lambda: errors and controller.process is None)
	assert len(errors) == 1 and errors[0][0] == 7
	assert controller.job is None and not controller.deadline.isActive()
	controller.shutdown()
''')

	def test_rapid_reopen_uses_one_process(self):
		self.run_qt('''
with TemporaryDirectory() as directory:
	path = Path(directory) / 'report.pdf'
	path.write_bytes(pdf_bytes())
	controller = PdfController()
	documents = []
	controller.document_ready.connect(lambda *args: documents.append(args))
	controller.open(1, str(path))
	first = controller.process
	for generation in range(2, 20):
		controller.open(generation, str(path))
		assert controller.process is first
	until(lambda: documents)
	assert [result[0] for result in documents] == [19]
	controller.invalidate()
	until(lambda: controller.process is None)
	controller.shutdown()
''')

	def test_open_and_render_deadlines(self):
		self.run_qt('''
import fman.impl.quick_view_pdf as module
module.OPEN_TIMEOUT = module.RENDER_TIMEOUT = 100
for stage in ('open', 'render'):
	script = """
from _quick_view_pdf_worker import encode_frame, read_command
from threading import Event
import sys
sys.stdout.buffer.write(encode_frame({'type':'ready'})); sys.stdout.buffer.flush()
request = read_command(sys.stdin.buffer)
if STAGE == 'render':
	request.update(type='document', sizes=[[200,200]], fingerprint=[1,2,3,4])
	sys.stdout.buffer.write(encode_frame(request)); sys.stdout.buffer.flush()
	read_command(sys.stdin.buffer)
Event().wait()
""".replace('STAGE', repr(stage))
	controller = PdfController(command=[sys.executable, '-B', '-c', script])
	controller.document_ready.connect(lambda generation, *args: controller.request_pages(generation, 1, ((0, 200, 200),)))
	errors = []
	controller.failed.connect(lambda *args: errors.append(args))
	controller.open(1, 'unused.pdf')
	until(lambda: errors and controller.process is None)
	assert errors == [(1, 'PDF preview timed out')], errors
	controller.shutdown()
''')

	def test_canvas_controls_bounds_and_keyboard(self):
		self.run_qt('''
from fman.impl.quick_view_pdf_view import PdfPreview, CACHE_BYTES
from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from unittest.mock import Mock
source = QWidget()
source._controller = Mock()
view = PdfPreview(source)
view.resize(620, 740)
view.show()
app.processEvents()
canvas = view.canvas
canvas.set_document(((200, 400), (400, 200), (200, 400)))
assert view.buttons['fit_page'].isChecked()
assert not view.buttons['previous'].isEnabled()
QTest.mouseClick(view.buttons['fit_width'], Qt.LeftButton)
assert canvas.mode == 'fit_width'
canvas.go_to(1)
assert abs(canvas._offset()[1] - canvas.rects[1].top()) < 1
view.page_input.setText('3')
QTest.keyClick(view.page_input, Qt.Key_Return)
assert canvas.current_page == 2
view.page_input.setText('9999')
QTest.keyClick(view.page_input, Qt.Key_Return)
assert view.page_input.text() == '3'
QTest.keyClick(canvas, Qt.Key_Minus)
assert canvas.mode == 'manual'
assert .25 <= canvas.zoom <= 4
QTest.keyClick(canvas, Qt.Key_F)
assert canvas.mode == 'fit_page'
QTest.keyClick(canvas, Qt.Key_F9)
assert source._controller.handle_shortcut.call_count == 1
view.resize(320, 640)
app.processEvents()
assert view._columns < 3
assert all(group.geometry().right() < view.width() for group in view.groups)
canvas.set_document(((10000000, 10000000),) * 2000)
canvas.zoom_by(40)
assert canvas.verticalScrollBar().maximum() <= 1000000000
canvas.clear()
assert canvas.cache_bytes == 0 and not canvas.timer.isActive()
view.close()
''')

	def test_parent_exit_reaps_owned_helper(self):
		if sys.platform != 'win32':
			self.skipTest('Windows Job Object')
		import win32api
		import win32con
		import win32event
		code = '''
from fman.impl.quick_view_pdf import PdfController
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
import os, sys
app = QApplication([])
controller = PdfController(command=[sys.executable, '-B', '-c', 'from threading import Event; Event().wait()'])
controller.open(1, 'unused.pdf')
def owned():
	assert controller.job is not None
	print(controller.process.processId(), flush=True)
	sys.stdin.readline()
	os._exit(0)
if controller.job is not None:
	QTimer.singleShot(0, owned)
else:
	controller.process.started.connect(owned)
QTimer.singleShot(5000, lambda: os._exit(2))
app.exec_()
'''
		parent = subprocess.Popen([sys.executable, '-B', '-c', code], stdin=subprocess.PIPE,
			stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(os.environ, QT_QPA_PLATFORM='offscreen'))
		child_handle = None
		try:
			pid = parent.stdout.readline()
			self.assertTrue(pid, 'Test parent did not acquire child ownership')
			child_handle = win32api.OpenProcess(win32con.SYNCHRONIZE, False, int(pid))
			output, errors = parent.communicate(b'exit\n', timeout=10)
			self.assertEqual(0, parent.returncode, errors)
			self.assertEqual(win32event.WAIT_OBJECT_0, win32event.WaitForSingleObject(child_handle, 5000))
		finally:
			if child_handle is not None:
				child_handle.Close()
			if parent.poll() is None:
				parent.kill()
			parent.communicate(timeout=5)

	def test_repeated_use_and_large_pixel_delivery(self):
		self.run_qt('''
from fman.impl.quick_view_pdf_view import PdfPreview
from PyQt5.QtWidgets import QWidget
from ctypes import WinDLL, POINTER, byref, wintypes
from time import perf_counter
import win32api, win32process
kernel = WinDLL('kernel32', use_last_error=True)
kernel.GetProcessHandleCount.argtypes = (wintypes.HANDLE, POINTER(wintypes.DWORD))
kernel.GetProcessHandleCount.restype = wintypes.BOOL
def usage():
	handles = wintypes.DWORD()
	assert kernel.GetProcessHandleCount(int(win32api.GetCurrentProcess()), byref(handles))
	return handles.value, win32process.GetProcessMemoryInfo(win32api.GetCurrentProcess())['PagefileUsage']
with TemporaryDirectory() as directory:
	path = Path(directory) / 'report.pdf'
	path.write_bytes(pdf_bytes())
	source = QWidget()
	view = PdfPreview(source)
	view.resize(620, 740)
	view.show()
	app.processEvents()
	canvas = view.canvas
	controller = PdfController()
	documents, errors, copies, latencies, samples, gaps = [], [], [], [], [], []
	controller.document_ready.connect(lambda *args: documents.append(args))
	controller.failed.connect(lambda *args: errors.append(args))
	def rendered(generation, revision, request, result):
		start = perf_counter()
		canvas.set_page(revision, request, result)
		copies.append((perf_counter() - start) * 1000)
	controller.page_ready.connect(rendered)
	for generation in range(100):
		documents.clear()
		canvas.clear()
		start = perf_counter()
		controller.open(generation, str(path))
		until(lambda: documents or errors)
		assert not errors, errors
		canvas.set_document(documents[0][1])
		canvas.timer.stop()
		controller.request_pages(generation, canvas.revision, ((0, 200, 200),))
		until(lambda: bool(canvas.cache) or errors)
		assert not errors, errors
		latencies.append((perf_counter() - start) * 1000)
		controller.invalidate()
		until(lambda: controller.process is None)
		canvas.clear()
		assert controller.job is None and controller._active is None
		assert not controller.deadline.isActive() and not controller.drain.isActive()
		assert not controller._decoder.buffer and not canvas.cache and canvas.cache_bytes == 0
		samples.append(usage())
	assert samples[-1][0] <= samples[9][0] + 4, samples
	assert samples[-1][1] <= samples[9][1] + 16 * 1024 * 1024, samples
	documents.clear()
	controller.open(101, str(path))
	until(lambda: documents)
	canvas.set_document(documents[0][1])
	canvas.timer.stop()
	last_tick = [perf_counter()]
	heartbeat = QTimer()
	def tick():
		now = perf_counter()
		gaps.append((now - last_tick[0]) * 1000)
		last_tick[0] = now
	heartbeat.timeout.connect(tick)
	heartbeat.start(5)
	baseline_copies = len(copies)
	controller.request_pages(101, canvas.revision, ((0, 2828, 2828),))
	until(lambda: len(copies) > baseline_copies or errors)
	tick()
	heartbeat.stop()
	assert not errors, errors
	assert max(gaps) < 100, gaps
	assert canvas.cache_bytes <= 64 * 1024 * 1024 and len(canvas.cache) <= 6
	assert next(iter(canvas.cache.values())).width() == 2828
	print('PDF_RESOURCE cycles=100 first_ms=%.1f median_ms=%.1f handles=%d->%d commit_MiB=%.1f->%.1f max_heartbeat_ms=%.1f large_copy_ms=%.1f' %
		(latencies[0], sorted(latencies)[50], samples[9][0], samples[-1][0], samples[9][1]/1048576,
		samples[-1][1]/1048576, max(gaps), copies[-1]))
	controller.invalidate()
	until(lambda: controller.process is None)
	controller.shutdown()
	view.close()
''')