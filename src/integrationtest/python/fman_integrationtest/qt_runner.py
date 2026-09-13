from fman.impl.util.qt.thread import run_in_main_thread
from PyQt5.QtCore import QCoreApplication, QEvent, QTimer
from PyQt5.QtWidgets import QApplication
from threading import Thread
from unittest import TestLoader, TextTestRunner

import sys


def main():
	app = QApplication([])
	app.setQuitOnLastWindowClosed(False)
	results = []
	def run():
		try:
			suite = TestLoader().loadTestsFromNames(sys.argv[1:])
			results.append(TextTestRunner(verbosity=2).run(suite))
		finally:
			run_in_main_thread(app.quit)()
	worker = Thread(target=run)
	QTimer.singleShot(0, worker.start)
	app.exec_()
	worker.join()
	QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
	return 0 if results and results[0].wasSuccessful() else 1


if __name__ == '__main__':
	sys.exit(main())