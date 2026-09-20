from subprocess import list2cmdline

import os


MAX_COMMAND_UNITS = 32766


def _check_text(value):
	if not isinstance(value, str) or '\0' in value:
		raise ValueError('Executable and arguments must be text without NUL characters.')
	if len(value.encode('utf-16-le')) // 2 > MAX_COMMAND_UNITS:
		raise ValueError('The command is too long.')


def parse_arguments(text):
	_check_text(text)
	if not text.strip():
		return []
	import ctypes
	from ctypes import wintypes
	command = 'program.exe ' + text
	_check_text(command)
	shell = ctypes.WinDLL('shell32', use_last_error=True)
	kernel = ctypes.WinDLL('kernel32', use_last_error=True)
	shell.CommandLineToArgvW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int))
	shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
	kernel.LocalFree.argtypes = (wintypes.HLOCAL,)
	kernel.LocalFree.restype = wintypes.HLOCAL
	count = ctypes.c_int()
	arguments = shell.CommandLineToArgvW(command, ctypes.byref(count))
	if not arguments:
		raise ctypes.WinError(ctypes.get_last_error())
	try:
		return list(arguments[1:count.value])
	finally:
		kernel.LocalFree(ctypes.cast(arguments, wintypes.HLOCAL))


def _check_argv(arguments):
	if not isinstance(arguments, list) or not arguments:
		raise ValueError('The command must contain an executable and an argument list.')
	for argument in arguments:
		_check_text(argument)
	_check_text(list2cmdline(arguments))
	if not arguments[0] or not os.path.isfile(arguments[0]):
		raise ValueError('The configured executable was not found.')