from fman.impl.shell_items import dropped_urls, forget_failure
from fman.impl.util.qt import as_qurl
from fman.impl.util.qt.thread import run_in_main_thread
from PyQt5.QtCore import QMimeData
from PyQt5.QtWidgets import QApplication

import struct

_CFSTR_PREFERREDDROPEFFECT = 'Preferred DropEffect'
_CF_PREFERREDDROPEFFECT = \
	'application/x-qt-windows-mime;value="%s"' % _CFSTR_PREFERREDDROPEFFECT
_DROPEFFECT_MOVE = struct.pack('i', 2)

@run_in_main_thread
def clear():
	_clipboard().clear()

@run_in_main_thread
def set_text(text):
	_clipboard().setText(text)

@run_in_main_thread
def get_text():
	return _clipboard().text()

@run_in_main_thread
def copy_files(file_urls):
	extra_data = {}
	_place_on_clipboard(file_urls, extra_data)

@run_in_main_thread
def cut_files(file_urls):
	extra_data = {
		# Make pasting work in Explorer:
		_CFSTR_PREFERREDDROPEFFECT: _DROPEFFECT_MOVE,
		# Make pasting work in Qt:
		_CF_PREFERREDDROPEFFECT: _DROPEFFECT_MOVE
	}
	_place_on_clipboard(file_urls, extra_data)

@run_in_main_thread
def get_files():
	"""File URLs on the clipboard. Items copied in Explorer's archive view are
	returned as archive URLs, e.g. zip://C:/a.zip/folder; none if any cannot be mapped."""
	forget_failure()
	return dropped_urls(_clipboard().mimeData())[0]

@run_in_main_thread
def files_were_cut():
	mime = _clipboard().mimeData()
	# Items cut in Explorer's archive view are only copied: never change the archive.
	if dropped_urls(mime)[1]:
		return False
	return mime.data(_CF_PREFERREDDROPEFFECT) == _DROPEFFECT_MOVE

def _clipboard():
	return QApplication.instance().clipboard()

def _place_on_clipboard(file_urls, extra_data):
	urls = [as_qurl(url) for url in file_urls]
	new_clipboard_data = QMimeData()
	new_clipboard_data.setUrls(urls)
	# We overwrite the "URLs" part of the clipboard, but we do want to keep the
	# text. This for instance allows for the following use case:
	#  1) Copy a file name
	#  2) Ctrl+C another file
	#  3) Ctrl+V to paste (=duplicate) the file
	#  4) Ctrl+V in the dialog to paste the file name we copied in 1).
	new_clipboard_data.setText(get_text())
	for key, value in extra_data.items():
		new_clipboard_data.setData(key, value)
	_clipboard().setMimeData(new_clipboard_data)
