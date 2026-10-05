from _quick_view_pdf_worker import (
	FrameDecoder, IDENTITY, MAX_HEADER, MAX_PAGES, MAX_PAYLOAD, PdfError,
	encode_frame, valid_geometry, valid_raster
)
from pathlib import Path
from PyQt5.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication

import sys
import weakref


START_TIMEOUT = 5000
OPEN_TIMEOUT = 15000
RENDER_TIMEOUT = 5000
DRAIN_BYTES = 256 * 1024


class ProcessJob:
	def __init__(self, pid):
		import win32api
		import win32con
		import win32job
		self.handle = win32job.CreateJobObject(None, '')
		try:
			info = win32job.QueryInformationJobObject(self.handle, win32job.JobObjectExtendedLimitInformation)
			info['BasicLimitInformation']['LimitFlags'] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
			win32job.SetInformationJobObject(self.handle, win32job.JobObjectExtendedLimitInformation, info)
			process = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, pid)
			try:
				win32job.AssignProcessToJobObject(self.handle, process)
			finally:
				process.Close()
		except Exception:
			self.close()
			raise

	def close(self):
		if self.handle is not None:
			self.handle.Close()
			self.handle = None


class PdfController(QObject):
	document_ready = pyqtSignal(int, object, object)
	page_ready = pyqtSignal(int, int, object, object)
	page_failed = pyqtSignal(int, int, str)
	failed = pyqtSignal(int, str)

	def __init__(self, window=None, command=None):
		super().__init__(QApplication.instance())
		self._window = weakref.ref(window) if window is not None else lambda: None
		self._command = command
		self.process = None
		self.job = None
		self._generation = None
		self._epoch = 0
		self._operation = 0
		self._revision = 0
		self._active = None
		self._next = None
		self._targets = ()
		self._sizes = ()
		self._fingerprint = ()
		self._ready = False
		self._retiring = False
		self._disposed = False
		self._decoder = FrameDecoder()
		self.stderr = bytearray()
		self.deadline = QTimer(self)
		self.deadline.setSingleShot(True)
		self.deadline.timeout.connect(self._timeout)
		self.drain = QTimer(self)
		self.drain.setSingleShot(True)
		self.drain.timeout.connect(self._read)
		QApplication.instance().aboutToQuit.connect(self.shutdown)
		if window is not None:
			window.closed.connect(self.shutdown)

	def open(self, generation, path):
		if self._disposed:
			return
		self.invalidate()
		self._generation = generation
		self._next = path
		if self.process is None:
			self._start()

	def invalidate(self):
		self._generation = self._next = None
		self._targets = self._sizes = self._fingerprint = ()
		if self.process is not None and not self._retiring:
			self._retiring = True
			if self._ready and self._active is None and self.process.state() == QProcess.Running:
				self._send('close', 250)
			else:
				self._kill()

	def request_pages(self, generation, revision, targets):
		if generation != self._generation or self._retiring:
			return
		self._revision = revision
		self._targets = tuple(targets)
		self._pump()

	def _start(self):
		self._epoch += 1
		self._ready = self._retiring = False
		self._active = None
		self._decoder = FrameDecoder()
		self.stderr.clear()
		process = self.process = QProcess(self)
		if self._command is not None:
			program, *arguments = self._command
		elif getattr(sys, 'frozen', False):
			program, arguments = sys.executable, ['--quick-view-pdf-worker']
		else:
			entry = Path(__file__).resolve().parents[1] / 'main.py'
			program, arguments = sys.executable, ['-B', str(entry), '--quick-view-pdf-worker']
			environment = QProcessEnvironment.systemEnvironment()
			environment.insert('PYTHONPATH', str(entry.parent.parent))
			process.setProcessEnvironment(environment)
		process.setWorkingDirectory(str(Path(sys.executable).parent))
		process.started.connect(self._started)
		process.readyReadStandardOutput.connect(self._read)
		process.readyReadStandardError.connect(self._read_error)
		process.finished.connect(self._finished)
		process.errorOccurred.connect(self._process_error)
		self.deadline.start(START_TIMEOUT)
		process.start(program, arguments)

	def _started(self):
		process = self.process
		if process is None:
			return
		if self._retiring:
			self._kill()
			return
		try:
			self.job = ProcessJob(int(process.processId()))
		except Exception:
			self._fail('Cannot safely start PDF renderer')

	def _send(self, kind, timeout, **values):
		self._operation += 1
		self._active = dict(type=kind, epoch=self._epoch, generation=self._generation or 0,
			operation=self._operation, revision=self._revision, **values)
		self.deadline.start(timeout)
		self.process.write(encode_frame(self._active))

	def _pump(self):
		if not self._ready or self._retiring or self._active is not None:
			return
		if self._next is not None:
			path, self._next = self._next, None
			self._send('open', OPEN_TIMEOUT, path=path)
		elif self._sizes and self._targets:
			page, width, height = self._targets[0]
			self._targets = self._targets[1:]
			if type(page) is not int or not 0 <= page < len(self._sizes) or not valid_raster(width, height):
				self._fail('Invalid PDF render request')
				return
			self._send('render', RENDER_TIMEOUT, page=page, width=width, height=height)

	def _read(self):
		process = self.process
		if process is None:
			return
		if process.bytesAvailable() + len(self._decoder.buffer) > MAX_HEADER + MAX_PAYLOAD + 4:
			self._fail('PDF renderer output exceeds limit')
			return
		try:
			frames = self._decoder.feed(bytes(process.read(DRAIN_BYTES)))
			if self._retiring:
				return
			if len(frames) > 1:
				raise PdfError('Unexpected PDF renderer messages')
			for header, payload in frames:
				self._receive(header, payload)
		except (PdfError, TypeError, KeyError, OverflowError):
			self._fail('Invalid PDF renderer response')
			return
		if process is self.process and process.bytesAvailable() and not self.drain.isActive():
			self.drain.start(0)

	def _receive(self, header, payload):
		kind = header.get('type')
		if not self._ready:
			if kind != 'ready' or payload or self.job is None:
				raise PdfError('Invalid PDF renderer startup')
			self._ready = True
			self.deadline.stop()
			self._pump()
			return
		active = self._active
		if active is None or any(type(header.get(key)) is not int or header[key] != active[key] for key in IDENTITY):
			raise PdfError('Unexpected PDF renderer response')
		generation, revision = active['generation'], active['revision']
		if kind == 'error':
			message = header.get('message')
			if payload or not isinstance(message, str) or len(message) > 512:
				raise PdfError('Invalid PDF renderer error')
			self._active = None
			self.deadline.stop()
			if active['type'] != 'render':
				self._fail(message)
				return
			if type(header.get('page')) is not int or header['page'] != active['page']:
				raise PdfError('Invalid PDF page error')
			if revision == self._revision:
				self.page_failed.emit(generation, active['page'], message)
		elif kind == 'document' and active['type'] == 'open':
			sizes, fingerprint = header.get('sizes'), header.get('fingerprint')
			if (payload or not isinstance(sizes, list) or not 0 < len(sizes) <= MAX_PAGES or
				not all(valid_geometry(size) for size in sizes) or not isinstance(fingerprint, list) or
				len(fingerprint) != 4 or any(type(value) is not int for value in fingerprint)):
				raise PdfError('Invalid PDF metadata')
			self._sizes = tuple(tuple(size) for size in sizes)
			self._fingerprint = tuple(fingerprint)
			self._active = None
			self.deadline.stop()
			self.document_ready.emit(generation, self._sizes, self._fingerprint)
		elif kind == 'page' and active['type'] == 'render':
			width, height = header.get('width'), header.get('height')
			if (not valid_raster(width, height) or width > active['width'] or height > active['height'] or
				type(header.get('stride')) is not int or header['stride'] != width * 4 or len(payload) != width * height * 4 or
				type(header.get('page')) is not int or header['page'] != active['page'] or header.get('fingerprint') != list(self._fingerprint)):
				raise PdfError('Invalid PDF pixels')
			self._active = None
			self.deadline.stop()
			if revision == self._revision:
				self.page_ready.emit(generation, revision, active, (header, payload))
		else:
			raise PdfError('Unexpected PDF renderer response')
		self._pump()

	def _read_error(self):
		process = self.process
		if process is None:
			return
		process.setReadChannel(QProcess.StandardError)
		data = bytes(process.read(65537))
		remaining = process.bytesAvailable()
		process.setReadChannel(QProcess.StandardOutput)
		allowance = max(0, 65536 - len(self.stderr))
		self.stderr.extend(data[:allowance])
		if len(data) > allowance or remaining:
			self._fail('PDF renderer diagnostic output exceeds limit')

	def _timeout(self):
		if self._retiring:
			self._kill()
		else:
			self._fail('PDF preview timed out')

	def _fail(self, message):
		generation = self._generation
		self._generation = self._next = None
		self._targets = self._sizes = self._fingerprint = ()
		if not self._retiring and generation is not None:
			self.failed.emit(generation, message)
		self._retiring = True
		self._kill()

	def _kill(self):
		self.deadline.stop()
		self.drain.stop()
		if self.job is not None:
			self.job.close()
			self.job = None
		if self.process is not None:
			self.process.kill()

	def _process_error(self, error):
		if self._retiring:
			return
		self._fail('PDF renderer could not start' if error == QProcess.FailedToStart else 'PDF renderer stopped unexpectedly')
		if error == QProcess.FailedToStart:
			self._finished()

	def _finished(self, *_):
		if self.process is None:
			return
		if not self._retiring:
			self._fail('PDF renderer stopped unexpectedly')
		self.deadline.stop()
		self.drain.stop()
		if self.job is not None:
			self.job.close()
			self.job = None
		self.process.deleteLater()
		self.process = None
		self._active = None
		self._decoder = FrameDecoder()
		self._ready = self._retiring = False
		if self._disposed:
			self.deleteLater()
		elif self._next is not None:
			self._start()

	def shutdown(self):
		self._disposed = True
		self.invalidate()
		self._kill()
		if self.process is None:
			self.deleteLater()