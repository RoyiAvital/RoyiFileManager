from contextlib import contextmanager
from threading import BoundedSemaphore, Event, RLock, local


_context = local()
_initialization_slots = BoundedSemaphore(2)


def current_request():
	return getattr(_context, 'request', None)


@contextmanager
def tracking(request):
	previous = current_request()
	_context.request = request
	try:
		yield
	finally:
		_context.request = previous


class NavigationRequest:
	def __init__(self, deliver, allowed=lambda: True):
		self._deliver = deliver
		self._allowed = allowed
		self._lock = RLock()
		self.done = False
		self.started = False
		self.settled = Event()
		self.pane = None
		self._initializing = False

	@property
	def active(self):
		return not self.done and self._allowed()

	def finish(self, outcome, message=''):
		with self._lock:
			if self.done:
				return
			self.done = True
			deliver = self._deliver
			self._deliver = None
			self._allowed = lambda: False
			self.pane = None
			self.settled.set()
		deliver(outcome, message)

	def begin_initialization(self):
		with self._lock:
			if not self.active:
				self.cancel()
				return False
			if not _initialization_slots.acquire(blocking=False):
				self.fail('Earlier directory checks are still finishing. Please try again.')
				return False
			self._initializing = True
			return True

	def end_initialization(self):
		with self._lock:
			if self._initializing:
				self._initializing = False
				_initialization_slots.release()

	def wait(self, timeout=30):
		if not self.settled.wait(timeout):
			self.fail('Directory navigation timed out; its filesystem check may still be finishing.')

	def fail(self, error):
		self.finish('failure', str(error))

	def cancel(self):
		self.finish('superseded')

	def dispatch(self, pane, url):
		if not self.active:
			self.cancel()
			return
		self.pane = pane
		try:
			with tracking(self):
				pane.run_command('open_directory', {'url': url})
		except Exception as error:
			self.fail(error)
		if not self.started and not self.done:
			self.fail('The command did not start a tracked directory navigation.')