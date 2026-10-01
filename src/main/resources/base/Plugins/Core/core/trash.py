from errno import EINVAL
from os import strerror

def move_to_trash(*files):
	send2trash = _import_send2trash()
	for file in files:
		try:
			send2trash(file)
		except OSError as e:
			if e.errno == EINVAL and e.winerror == _DE_INVALIDFILES:
				message = strerror(EINVAL) + ' (file may be in use)'
				raise OSError(EINVAL, message)
			raise

def _import_send2trash():
	from send2trash import send2trash as result
	return result

# Windows constant:
_DE_INVALIDFILES = 0x7C