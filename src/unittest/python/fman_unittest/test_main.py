from unittest import TestCase
import subprocess
import sys

_SCRIPT = '''
import atexit, time
from threading import Thread
from unittest.mock import patch
from fman import main

class Context:
	def run(self):
		print('buffered')
		atexit.register(print, 'exit handler ran')
		Thread(target=lambda: (time.sleep(0.2), print('thread finished'))).start()
		return 3

with patch('fman.impl.application_context.get_application_context', Context):
	main.main()
'''

class MainExitTest(TestCase):
	def test_exit_runs_threads_and_handlers_then_skips_teardown(self):
		completed = subprocess.run([sys.executable, '-c', _SCRIPT], capture_output=True, text=True, timeout=60)
		self.assertEqual(3, completed.returncode, completed.stderr)
		self.assertEqual(['buffered', 'thread finished', 'exit handler ran'], completed.stdout.splitlines())
