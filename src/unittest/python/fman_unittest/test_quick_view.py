from fman.impl.quick_view_images import ImageLoader, ImageRequest, ImageResult
from threading import Event
from unittest import TestCase

import os
import subprocess
import sys


class ImageLoaderTest(TestCase):
	def test_independent_loaders_do_not_block_each_other(self):
		started, release, delivered = Event(), Event(), Event()
		def blocked(request, canceled):
			started.set()
			release.wait(5)
			return ImageResult()
		first = ImageLoader(lambda: None, blocked)
		second = ImageLoader(delivered.set, lambda request, canceled: ImageResult(message='second'))
		self.addCleanup(first.close)
		self.addCleanup(second.close)
		self.addCleanup(release.set)
		first.submit(ImageRequest(first.invalidate(), 'blocked'))
		self.assertTrue(started.wait(5))
		second.submit(ImageRequest(second.invalidate(), 'free'))
		self.assertTrue(delivered.wait(5))
		self.assertEqual('second', second.take_result()[1].message)
		self.assertTrue(first.busy)

	def test_latest_request_replaces_pending_and_rejects_stale(self):
		started, release, delivered = Event(), Event(), Event()
		loaded = []
		def load(request, canceled):
			loaded.append(request.url)
			if request.url == 'first':
				started.set()
				release.wait(5)
				self.assertTrue(canceled())
			return ImageResult(message=request.url)
		loader = ImageLoader(delivered.set, load)
		self.addCleanup(loader.close)
		self.addCleanup(release.set)
		loader.submit(ImageRequest(loader.invalidate(), 'first'))
		self.assertTrue(started.wait(5))
		worker = loader._thread
		for index in range(200):
			loader.submit(ImageRequest(loader.invalidate(), str(index)))
		self.assertIs(worker, loader._thread)
		release.set()
		self.assertTrue(delivered.wait(5))
		self.assertEqual(['first', '199'], loaded)
		self.assertEqual('199', loader.take_result()[1].message)
		worker.join(5)
		self.assertFalse(worker.is_alive())

	def test_undelivered_result_blocks_next_decode(self):
		delivered = Event()
		loaded = []
		def load(request, canceled):
			loaded.append(request.url)
			return ImageResult(message=request.url)
		loader = ImageLoader(delivered.set, load)
		self.addCleanup(loader.close)
		generation = loader.invalidate()
		loader.submit(ImageRequest(generation, 'first'))
		self.assertTrue(delivered.wait(5))
		for index in range(200):
			loader.submit(ImageRequest(generation, str(index)))
		with loader._condition:
			self.assertEqual(['first'], loaded)
			self.assertEqual('199', loader._pending.url)
		delivered.clear()
		self.assertEqual('first', loader.take_result()[1].message)
		self.assertTrue(delivered.wait(5))
		self.assertEqual(['first', '199'], loaded)
		self.assertEqual('199', loader.take_result()[1].message)

	def test_close_drops_late_result_without_notifying(self):
		started, release, delivered = Event(), Event(), Event()
		def load(request, canceled):
			started.set()
			release.wait(5)
			return ImageResult(message='late')
		loader = ImageLoader(delivered.set, load)
		self.addCleanup(release.set)
		loader.submit(ImageRequest(loader.invalidate(), 'file'))
		self.assertTrue(started.wait(5))
		worker = loader._thread
		loader.close()
		release.set()
		worker.join(5)
		self.assertFalse(worker.is_alive())
		self.assertIsNone(loader.take_result())
		self.assertFalse(delivered.is_set())

	def test_blocked_read_does_not_prevent_process_exit(self):
		code = '''
from fman.impl.quick_view_images import ImageLoader, ImageRequest
from threading import Event
started = Event()
def load(request, canceled):
    started.set()
    Event().wait()
loader = ImageLoader(lambda: None, load)
loader.submit(ImageRequest(loader.invalidate(), 'blocked'))
assert started.wait(2)
loader.close()
print('closed', flush=True)
'''
		result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=10)
		self.assertEqual(0, result.returncode, result.stderr)
		self.assertIn('closed', result.stdout)


class QuickViewClipboardTest(TestCase):
	def test_image_clipboard_round_trip_and_file_copy(self):
		code = '''
from fman import clipboard
from fman.impl.quick_view import QuickViewSession
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtWidgets import QApplication
from types import SimpleNamespace

app = QApplication([])
image = QImage(32, 24, QImage.Format_ARGB32_Premultiplied)
image.fill(QColor('#80402010'))
expected = image.copy()
canvas = SimpleNamespace(image=image)
session = SimpleNamespace(overlay=SimpleNamespace(canvas=canvas))
files = ['file://C:/quick-view.png']
clipboard.cut_files(files)
assert clipboard.files_were_cut()
QuickViewSession.image_action(session, 'copy_image')
assert QApplication.clipboard().mimeData().hasImage()
assert QApplication.clipboard().image() == expected
assert clipboard.get_files() == []
assert not clipboard.files_were_cut()
canvas.image = None
del image
QuickViewSession.image_action(session, 'copy_image')
del session, canvas
assert QApplication.clipboard().image() == expected
clipboard.copy_files(files)
assert clipboard.get_files() == files
assert not clipboard.files_were_cut()
assert not QApplication.clipboard().mimeData().hasImage()
clipboard.clear()
'''
		result = subprocess.run(
			[sys.executable, '-c', code], env=dict(os.environ, QT_QPA_PLATFORM='offscreen'),
			capture_output=True, text=True, timeout=30)
		self.assertEqual(0, result.returncode, result.stdout + result.stderr)


class QuickViewPackagingTest(TestCase):
	def test_lazy_renderer_is_collected(self):
		import ast
		from pathlib import Path
		root = Path(__file__).resolve().parents[4]
		tree = ast.parse((root / 'RoyiFileManager.spec').read_text(encoding='utf-8'))
		assignment = next(node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'hidden_imports' for target in node.targets))
		self.assertIn('fman.impl.quick_view', [node.value for node in ast.walk(assignment.value) if isinstance(node, ast.Constant)])