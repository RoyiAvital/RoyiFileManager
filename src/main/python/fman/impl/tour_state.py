from threading import Lock


class TourState:
	__slots__ = ('_last', '_aborts', '_lock')

	def __init__(self):
		self._last = None
		self._aborts = 0
		self._lock = Lock()

	def finished(self, outcome):
		if outcome not in ('aborted', 'completed'):
			raise ValueError(outcome)
		with self._lock:
			self._last = outcome
			if outcome == 'aborted':
				self._aborts = min(2, self._aborts + 1)

	def activity(self):
		with self._lock:
			self._last = None

	def take(self):
		with self._lock:
			result = self._last, self._aborts
			self._last = None
			return result