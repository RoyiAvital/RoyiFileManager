import platform as stdlib_platform
import sys


def name():
	if is_windows():
		return 'Windows'
	if is_mac():
		return 'Mac'
	if is_linux():
		return 'Linux'
	return stdlib_platform.system()


def is_windows():
	return sys.platform == 'win32'


def is_mac():
	return sys.platform == 'darwin'


def is_linux():
	return sys.platform.startswith('linux')


def is_gnome_based():
	return False


def is_kde_based():
	return False


def is_ubuntu():
	return False


def is_fedora():
	return False


def is_arch_linux():
	return False


def linux_distribution():
	return ''