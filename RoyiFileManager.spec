from PyInstaller.utils.hooks import collect_all
from pathlib import Path
import os
import sys


winpty_datas, winpty_binaries, winpty_imports = collect_all('winpty')
send2trash_datas, send2trash_binaries, send2trash_imports = \
	collect_all('send2trash')

datas = [
	('src/main/resources/base', 'resources'),
	('src/build/settings/base.json', 'resources/build-settings'),
	('src/main/resources/windows', 'resources'),
	('src/main/icons/Icon.ico', 'resources')
] + winpty_datas + send2trash_datas
binaries = winpty_binaries + send2trash_binaries + [
	(str(Path(sys.prefix) / 'bin' / 'rg.exe'), 'resources/Plugins/SearchFileContent/bin')
]
hidden_imports = [
	'adodbapi', 'ctypes.wintypes', 'win32com.shell.shell',
	'win32com.shell.shellcon', 'win32gui', 'win32wnet', 'win32process',
	'fman.ui', 'fman.impl.ui.quicklist', 'fman.impl.ui.panel',
	'fman.impl.ui.session', 'fman.impl.ui.output', 'fman.impl.navigation',
	'fman.impl.ui.table', 'fman.impl.ui.table_data', 'fman.impl.ui.facade',
	'PyQt5.QtSvg'
] + winpty_imports + send2trash_imports

a = Analysis(
	['src/main/python/fman/main.py'],
	pathex=['src/main/python'],
	binaries=binaries,
	datas=datas,
	hiddenimports=hidden_imports,
	excludes=['boto3', 'botocore', 's3transfer']
)
pyz = PYZ(a.pure)
exe = EXE(
	pyz,
	a.scripts,
	[],
	exclude_binaries=True,
	name='RoyiFileManager',
	console=os.environ.get('ROYIFILEMANAGER_BUILD_CONSOLE') == '1',
	icon='src/main/icons/Icon.ico'
)
coll = COLLECT(
	exe,
	a.binaries,
	a.datas,
	strip=False,
	upx=True,
	name='RoyiFileManager'
)