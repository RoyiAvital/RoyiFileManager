from fman.impl.model.worker import Worker
from threading import Event
from unittest import TestCase


class WorkerTest(TestCase):
	def test_shutdown_from_worker_thread(self):
		worker = Worker()
		shutdown_returned = Event()
		worker.start()
		worker.submit(1, self._shutdown, worker, shutdown_returned)
		self.assertTrue(shutdown_returned.wait(1))
		worker._thread.join(1)
		self.assertFalse(worker._thread.is_alive())

	@staticmethod
	def _shutdown(worker, shutdown_returned):
		worker.shutdown()
		shutdown_returned.set()