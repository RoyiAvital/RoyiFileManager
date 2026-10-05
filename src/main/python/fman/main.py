import atexit
import logging
import os
import sys

if __name__ == '__main__' and sys.argv[1:] == ['--quick-view-pdf-worker']:
	from _quick_view_pdf_worker import main as pdf_worker_main
	sys.exit(pdf_worker_main())

from fman.impl.product import APP_NAME

def main():
	if sys.platform != 'win32':
		raise RuntimeError('%s is supported on Windows only.' % APP_NAME)
	# Registered first, so it runs after every other exit handler:
	atexit.register(_skip_interpreter_teardown)
	from fman.impl.application_context import get_application_context
	appctxt = get_application_context()
	exit_code = appctxt.run()
	_skip_interpreter_teardown.exit_code = exit_code
	sys.exit(exit_code)

def _skip_interpreter_teardown():
	# Destroying PyQt objects during interpreter teardown intermittently crashes in sip.
	logging.shutdown()
	sys.stdout.flush()
	sys.stderr.flush()
	os._exit(_skip_interpreter_teardown.exit_code)
_skip_interpreter_teardown.exit_code = 1

def profile_main():
	# Import late to only incur the .0n sec time cost when necessary:
	import cProfile
	from fbs_runtime.application_context import is_frozen
	filename = '%s.profile' % APP_NAME if is_frozen() else None
	cProfile.run('main()', sort='cumtime', filename=filename)

if __name__ == '__main__':
	if len(sys.argv) > 1 and sys.argv[1] == '--profile':
		sys.argv.pop(1)
		profile_main()
	else:
		main()