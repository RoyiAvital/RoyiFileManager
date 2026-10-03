import ctypes
from ctypes import wintypes
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass
from queue import Empty, Queue
import struct
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4


REQUEST_FLAGS = 0x8154
SORTS = {'name': 1, 'path': 3, 'size': 6, 'date_modified': 14}
MAX_PACKET_BYTES = 8 * 1024 * 1024


class IpcError(Exception):
	pass


class NotRunning(IpcError):
	pass


class QueryTimeout(IpcError):
	pass


class ProtocolError(IpcError):
	pass


@dataclass(frozen=True)
class Hit:
	path: str
	is_folder: bool
	size: int | None
	modified_ns: int | None
	highlight: tuple


@dataclass(frozen=True)
class Results:
	total: int
	hits: tuple


def encode_query(window, request_id, query, max_results=100, sort='name'):
	if '\0' in query or len(query) > 32767:
		raise ValueError('Invalid or excessively long Everything query.')
	if not 1 <= max_results <= 1000 or sort not in SORTS:
		raise ValueError('Invalid Everything result limit or sort.')
	return struct.pack('<7I', window & 0xffffffff, request_id, 0, 0,
		max_results, REQUEST_FLAGS, SORTS[sort]) + query.encode('utf-16-le') + b'\0\0'


def parse_highlight(text):
	plain, indices = [], []
	marked = False
	position = 0
	while position < len(text):
		character = text[position]
		if character == '*':
			if text[position:position + 2] == '**':
				position += 1
			else:
				marked = not marked
				position += 1
				continue
		if marked:
			indices.append(len(plain))
		plain.append(character)
		position += 1
	if marked:
		raise ProtocolError('Unclosed Everything highlight.')
	return ''.join(plain), tuple(indices)


def parse_reply(data, max_results=100):
	if not 20 <= len(data) <= MAX_PACKET_BYTES:
		raise ProtocolError('Invalid Everything reply size.')
	total, count, offset, flags, sort = struct.unpack_from('<5I', data)
	if flags != REQUEST_FLAGS or offset or count > min(total, max_results) or \
			20 + count * 8 > len(data) or sort not in SORTS.values():
		raise ProtocolError('Unsupported Everything reply header.')
	hits = []
	try:
		for index in range(count):
			item_flags, position = struct.unpack_from('<2I', data, 20 + index * 8)
			if position < 20 + count * 8:
				raise ProtocolError('Invalid Everything item offset.')

			def text():
				nonlocal position
				length, = struct.unpack_from('<I', data, position)
				position += 4
				end = position + length * 2
				if end + 2 > len(data) or data[end:end + 2] != b'\0\0':
					raise ProtocolError('Invalid Everything string length.')
				value = data[position:end].decode('utf-16-le')
				position = end + 2
				if '\0' in value:
					raise ProtocolError('Embedded NUL in Everything path.')
				return value

			path = text()
			size, modified, attributes = struct.unpack_from('<qQI', data, position)
			position += 20
			plain, highlight = parse_highlight(text())
			if plain != path:
				raise ProtocolError('Everything highlight does not match its path.')
			hits.append(Hit(path, bool(item_flags & 3 or attributes & 16),
				size if size >= 0 else None,
				(modified - 116444736000000000) * 100
				if modified not in (0, 0xffffffffffffffff) else None, highlight))
	except (struct.error, UnicodeError) as error:
		raise ProtocolError('Malformed Everything reply.') from error
	return Results(total, tuple(hits))


class CopyData(ctypes.Structure):
	_fields_ = [('tag', ctypes.c_size_t), ('size', wintypes.DWORD),
		('data', ctypes.c_void_p)]


class Native:
	def __init__(self):
		self.user = ctypes.WinDLL('user32', use_last_error=True)
		self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
		self.callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND,
			wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
		callback_type = self.callback_type

		class WindowClass(ctypes.Structure):
			_fields_ = [('style', wintypes.UINT), ('proc', callback_type),
				('class_extra', ctypes.c_int), ('window_extra', ctypes.c_int),
				('instance', wintypes.HINSTANCE), ('icon', wintypes.HICON),
				('cursor', wintypes.HANDLE), ('background', wintypes.HBRUSH),
				('menu', wintypes.LPCWSTR), ('name', wintypes.LPCWSTR)]

		self.window_class = WindowClass
		self.find = self.bind(self.user, 'FindWindowW', wintypes.HWND,
			wintypes.LPCWSTR, wintypes.LPCWSTR)
		self.send = self.bind(self.user, 'SendMessageTimeoutW', ctypes.c_ssize_t,
			wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
			wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t))
		self.register = self.bind(self.user, 'RegisterClassW', wintypes.ATOM,
			ctypes.POINTER(WindowClass))
		self.create = self.bind(self.user, 'CreateWindowExW', wintypes.HWND,
			wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
			ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
			wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p)
		self.default = self.bind(self.user, 'DefWindowProcW', ctypes.c_ssize_t,
			wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
		self.destroy = self.bind(self.user, 'DestroyWindow', wintypes.BOOL, wintypes.HWND)
		self.unregister = self.bind(self.user, 'UnregisterClassW', wintypes.BOOL,
			wintypes.LPCWSTR, wintypes.HINSTANCE)
		self.peek = self.bind(self.user, 'PeekMessageW', wintypes.BOOL,
			ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT,
			wintypes.UINT, wintypes.UINT)
		self.dispatch = self.bind(self.user, 'DispatchMessageW', ctypes.c_ssize_t,
			ctypes.POINTER(wintypes.MSG))
		self.wait = self.bind(self.user, 'MsgWaitForMultipleObjectsEx', wintypes.DWORD,
			wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
			wintypes.DWORD, wintypes.DWORD)
		self.create_event = self.bind(self.kernel, 'CreateEventW', wintypes.HANDLE,
			ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
		self.set_event = self.bind(self.kernel, 'SetEvent', wintypes.BOOL, wintypes.HANDLE)
		self.close_handle = self.bind(self.kernel, 'CloseHandle', wintypes.BOOL, wintypes.HANDLE)
		self.window_pid = self.bind(self.user, 'GetWindowThreadProcessId', wintypes.DWORD,
			wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
		self.open_process = self.bind(self.kernel, 'OpenProcess', wintypes.HANDLE,
			wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
		self.process_times = self.bind(self.kernel, 'GetProcessTimes', wintypes.BOOL,
			wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4))
		self.process_path = self.bind(self.kernel, 'QueryFullProcessImageNameW', wintypes.BOOL,
			wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))

	@staticmethod
	def bind(library, name, result, *arguments):
		function = getattr(library, name)
		function.restype, function.argtypes = result, arguments
		return function

	def find_instance(self, name):
		if not name or any(character in name for character in '()\\/\0'):
			raise ValueError('Everything requires a nonempty, simple instance name.')
		return self.find('EVERYTHING_TASKBAR_NOTIFICATION_(' + name + ')', None)

	def identity(self, window):
		pid = wintypes.DWORD()
		self.window_pid(window, ctypes.byref(pid))
		return self.identity_for_pid(pid.value)

	def identity_for_pid(self, pid):
		handle = self.open_process(0x1000, False, pid)
		if not handle:
			raise NotRunning('Cannot verify Everything process ownership.')
		try:
			times = [wintypes.FILETIME() for _ in range(4)]
			path = ctypes.create_unicode_buffer(32768)
			length = wintypes.DWORD(len(path))
			if not self.process_times(handle, *(ctypes.byref(value) for value in times)) or \
					not self.process_path(handle, 0, path, ctypes.byref(length)):
				raise NotRunning('Cannot verify Everything process identity.')
			created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
			return pid, created, path.value.casefold()
		finally:
			self.close_handle(handle)

	def probe(self, window, command, timeout=200):
		value = ctypes.c_size_t()
		if not window:
			raise NotRunning('Everything is not running.')
		if not self.send(window, 0x400, command, 0, 3, timeout, ctypes.byref(value)):
			raise QueryTimeout('Everything is busy.')
		return value.value

	def pump(self, wake, timeout):
		handles = (wintypes.HANDLE * 1)(wake)
		if self.wait(1, handles, timeout, 0x4ff, 4) == 0xffffffff:
			raise ctypes.WinError(ctypes.get_last_error())
		message = wintypes.MSG()
		while self.peek(ctypes.byref(message), None, 0, 0, 1):
			self.dispatch(ctypes.byref(message))


class IpcClient:
	def __init__(self):
		self._lock = Lock()
		self._ready = Event()
		self._closed = Event()
		self._queue = Queue()
		self._thread = None
		self._latest = 0
		self._error = None
		self._native = None
		self._wake = None

	def start(self, timeout=1):
		with self._lock:
			if self._closed.is_set():
				raise NotRunning('Everything client is closed.')
			if self._thread is None:
				self._thread = Thread(target=self._run, name='everything-ipc', daemon=True)
				self._thread.start()
		if not self._ready.wait(timeout):
			raise QueryTimeout('Starting Everything IPC.')
		if self._error:
			raise IpcError(str(self._error))
		if self._closed.is_set():
			raise NotRunning('Everything client is closed.')

	def query(self, instance, identity, query, max_results=100, sort='name', timeout_ms=50):
		deadline = monotonic() + min(500, max(1, timeout_ms)) / 1000
		self.start(max(0, deadline - monotonic()))
		future = Future()
		with self._lock:
			self._latest = self._latest % 0xffffffff + 1
			request_id = self._latest
			self._queue.put((request_id, instance, identity, query, max_results,
				sort, deadline, future))
			if self._wake:
				self._native.set_event(self._wake)
		try:
			return future.result(timeout=max(0, deadline - monotonic()))
		except FutureTimeout as error:
			future.cancel()
			raise QueryTimeout('Everything is busy; try the query again.') from error

	def _receive(self, window, message, sender, parameter):
		if message == 0x4a:
			if not parameter:
				return 0
			copied = ctypes.cast(parameter, ctypes.POINTER(CopyData)).contents
			if self._current == (copied.tag, sender) and copied.tag == self._latest:
				if copied.data and 20 <= copied.size <= MAX_PACKET_BYTES:
					self._reply = ctypes.string_at(copied.data, copied.size)
				else:
					self._reply = b''
				return 1
			return 0
		return self._native.default(window, message, sender, parameter)

	def _run(self):
		window = None
		name = 'RoyiFileManagerEverythingIPC_' + uuid4().hex
		registered = False
		try:
			self._native = native = Native()
			self._current, self._reply = None, None
			callback = native.callback_type(self._receive)
			window_class = native.window_class(proc=callback, name=name)
			registered = native.register(ctypes.byref(window_class))
			if not registered:
				raise ctypes.WinError(ctypes.get_last_error())
			window = native.create(0, name, '', 0, 0, 0, 0, 0, -3, None, None, None)
			self._wake = native.create_event(None, False, False, None)
			if not window or not self._wake:
				raise ctypes.WinError(ctypes.get_last_error())
			self._ready.set()
			while not self._closed.is_set():
				try:
					request = self._queue.get_nowait()
				except Empty:
					native.pump(self._wake, 0xffffffff)
					continue
				future = request[-1]
				if not future.set_running_or_notify_cancel():
					continue
				try:
					future.set_result(self._execute(window, request))
				except Exception as error:
					future.set_exception(error)
		except Exception as error:
			self._error = error
		finally:
			self._ready.set()
			with self._lock:
				if self._wake:
					self._native.close_handle(self._wake)
					self._wake = None
			if window:
				self._native.destroy(window)
			if registered:
				self._native.unregister(name, None)

	def _execute(self, window, request):
		request_id, instance, identity, query, limit, sort, deadline, future = request
		native = self._native
		target = native.find_instance(instance)
		if not target or native.identity(target) != identity:
			raise NotRunning('Everything instance changed.')
		data = encode_query(window, request_id, query, limit, sort)
		buffer = ctypes.create_string_buffer(data)
		copied = CopyData(18, len(data), ctypes.addressof(buffer))
		self._current, self._reply = (request_id, target), None
		remaining = int((deadline - monotonic()) * 1000)
		if remaining <= 0 or request_id != self._latest:
			raise QueryTimeout('Everything query was superseded or timed out.')
		value = ctypes.c_size_t()
		if not native.send(target, 0x4a, window, ctypes.addressof(copied), 3,
				remaining, ctypes.byref(value)):
			raise QueryTimeout('Everything did not accept the query in time.')
		if not value.value:
			raise ProtocolError('Everything does not support QUERY2W.')
		while self._reply is None:
			remaining = int((deadline - monotonic()) * 1000)
			if remaining <= 0 or self._closed.is_set() or request_id != self._latest:
				raise QueryTimeout('Everything query was superseded or timed out.')
			native.pump(self._wake, remaining)
		results = parse_reply(self._reply, limit)
		if self._closed.is_set() or request_id != self._latest or monotonic() >= deadline:
			raise QueryTimeout('Everything query was superseded or timed out.')
		return results

	def close(self, wait=True):
		self._closed.set()
		with self._lock:
			if self._wake:
				self._native.set_event(self._wake)
		if wait and self._thread:
			self._thread.join(0.6)