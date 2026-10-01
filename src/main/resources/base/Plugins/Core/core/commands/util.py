from PyQt5.QtCore import QFileInfo

import os

def get_program_files():
	return os.environ.get('PROGRAMW6432', r'C:\Program Files')

def get_program_files_x86():
	return os.environ.get('PROGRAMFILES', r'C:\Program Files (x86)')

def is_hidden(file_path):
	return QFileInfo(file_path).isHidden()