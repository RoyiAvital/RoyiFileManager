from traceback import print_exception


class ExceptionHandler:
	def handle(self, exc_type, exc_value, traceback):
		raise NotImplementedError()


class StderrExceptionHandler(ExceptionHandler):
	def handle(self, exc_type, exc_value, traceback):
		print_exception(exc_type, exc_value, traceback)
		return True