from dataclasses import dataclass
from html import escape
from pathlib import PureWindowsPath
from PyQt5.QtCore import QByteArray, QEvent, Qt, pyqtSignal
from PyQt5.QtGui import QFontDatabase, QFontMetricsF, QTextCursor, QTextDocument
from PyQt5.QtWidgets import (
	QApplication, QButtonGroup, QCheckBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QStyle,
	QTextBrowser, QToolButton, QVBoxLayout, QWidget
)

import codecs
import importlib
import locale
import os
import re
import stat


READ_LIMIT = 2 * 1024 * 1024
FORMAT_LIMIT = 512 * 1024
HTML_LIMIT = 8 * 1024 * 1024
PROBE_LIMIT = 8192
LANGUAGES = {
	'.py': 'python', '.pyw': 'python', '.jl': 'julia', '.js': 'javascript', '.jsx': 'jsx',
	'.m': 'matlab',
	'.ts': 'typescript', '.tsx': 'tsx', '.c': 'c', '.h': 'c', '.cpp': 'cpp',
	'.hpp': 'cpp', '.cc': 'cpp', '.cs': 'csharp', '.java': 'java', '.go': 'go',
	'.rs': 'rust', '.sh': 'bash', '.ps1': 'powershell', '.bat': 'batch',
	'.cmd': 'batch', '.sql': 'sql', '.html': 'html', '.htm': 'html', '.css': 'css',
	'.json': 'json', '.yaml': 'yaml', '.yml': 'yaml', '.toml': 'toml',
	'.xml': 'xml', '.svg': 'xml', '.ini': 'ini', '.diff': 'diff', '.patch': 'diff'
}
FILENAMES = {'makefile': 'make', 'cmakelists.txt': 'cmake', 'dockerfile': 'docker'}
MARKDOWN_SUFFIXES = frozenset(('.md', '.markdown', '.mdown'))
TEXT_SUFFIXES = frozenset(('.txt', '.log', '.cfg', '.conf', '.csv', '.tsv'))
BINARY_SUFFIXES = frozenset((
	'.exe', '.dll', '.zip', '.7z', '.tar', '.gz', '.bz2', '.xz', '.rar', '.iso',
	'.msi', '.pdf', '.mp4', '.mov', '.mkv', '.webm', '.avi', '.mpeg', '.mpg',
	'.ts', '.wmv', '.asf', '.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.pyc'
))


@dataclass(frozen=True)
class TextContent:
	text: str
	path: str
	encoding: str
	fingerprint: tuple
	byte_count: int
	warning: str = ''
	truncated: bool = False


@dataclass(frozen=True)
class TextResult:
	content: TextContent
	html: str = ''
	mode: str = 'source'
	message: str = ''
	kind: str = 'text'


def language_for(path):
	name = PureWindowsPath(path)
	return FILENAMES.get(name.name.lower(), LANGUAGES.get(name.suffix.lower(), ''))


def is_markdown(path):
	return PureWindowsPath(path).suffix.lower() in MARKDOWN_SUFFIXES


def decode_text(data, complete):
	encoding = 'utf-8'
	for marker, candidate in (
		(codecs.BOM_UTF32_LE, 'utf-32'), (codecs.BOM_UTF32_BE, 'utf-32'),
		(codecs.BOM_UTF16_LE, 'utf-16'), (codecs.BOM_UTF16_BE, 'utf-16'),
		(codecs.BOM_UTF8, 'utf-8-sig')
	):
		if data.startswith(marker):
			encoding = candidate
			break
	try:
		return codecs.getincrementaldecoder(encoding)().decode(data, final=complete), encoding, ''
	except UnicodeError:
		text = codecs.getincrementaldecoder(encoding)(errors='replace').decode(data, final=complete)
		if encoding == 'utf-8' and os.name == 'nt':
			valid_text = codecs.getincrementaldecoder(encoding)(errors='ignore').decode(data, final=complete)
			replacements = len(text) - len(valid_text)
			keep_utf8 = not valid_text.isascii() and replacements <= max(3, len(text) // 100)
			if not keep_utf8:
				ansi = locale.getencoding()
				try:
					return codecs.getincrementaldecoder(ansi)().decode(data, final=complete), ansi, 'Windows ANSI: ' + ansi
				except UnicodeError:
					pass
		return text, encoding, 'Encoding warning: replacement characters'


def is_binary(text):
	return '\0' in text or sum(ord(character) < 32 and character not in '\t\r\n\f'
		for character in text) > len(text) * .01


def convert_text(content, mode='rendered', colors=('#dddddd', '#252525'), canceled=lambda: False):
	if canceled():
		return None
	warning = content.warning
	if content.truncated:
		warning = ' | '.join(filter(None, (warning, 'Preview truncated at 2 MiB')))
	elif content.byte_count > FORMAT_LIMIT:
		warning = ' | '.join(filter(None, (warning, 'Formatting limited to 512 KiB')))
	language = language_for(content.path)
	markdown_file = is_markdown(content.path)
	if content.truncated or content.byte_count > FORMAT_LIMIT or mode == 'source' or not (language or markdown_file):
		return TextResult(content, message=warning)
	try:
		import markdown
		importlib.import_module('pygments')
		parser = markdown.Markdown(extensions=['fenced_code', 'tables', 'codehilite'],
			extension_configs={'codehilite': {'noclasses': True, 'guess_lang': False,
				'linenums': False, 'pygments_style': 'monokai', 'nobackground': True}})
		parser.preprocessors.deregister('html_block')
		parser.inlinePatterns.deregister('html')
		text = content.text
		if not markdown_file:
			fence = '`' * max(3, 1 + max((len(match.group()) for match in re.finditer(r'`+', text)), default=0))
			text = fence + language + '\n' + text + '\n' + fence
		body = parser.convert(text)
		foreground, background = colors
		html = '<html><body style="color:%s; background-color:%s">%s</body></html>' % (
			escape(foreground, quote=True), escape(background, quote=True), body)
		if len(html.encode('utf-8')) > HTML_LIMIT:
			return TextResult(content, message=' | '.join(filter(None, (warning, 'Formatting output exceeds 8 MiB'))))
		return None if canceled() else TextResult(content, html, 'rendered' if markdown_file else 'code', warning)
	except Exception:
		return None if canceled() else TextResult(content, message=' | '.join(filter(None, (warning, 'Formatting unavailable'))))


def load_text(request, canceled, resolve=None):
	from fman.impl.quick_view_images import ImageResult, _fingerprint, load_image
	from fman.url import as_human_readable, splitscheme
	def check():
		if canceled():
			raise InterruptedError()
	try:
		check()
		if not request.url or splitscheme(request.url)[0] != 'file://':
			return ImageResult(message='Only local files can be previewed', kind='error')
		if resolve is None:
			from fman.fs import resolve
		url = resolve(request.url)
		check()
		if splitscheme(url)[0] != 'file://':
			return ImageResult(message='Only local files can be previewed', kind='error')
		path = as_human_readable(url)
		suffix = PureWindowsPath(path).suffix.lower()
		known_text = language_for(path) or is_markdown(path) or suffix in TEXT_SUFFIXES
		if suffix in BINARY_SUFFIXES and not known_text:
			return ImageResult(message='Unsupported preview format', kind='unsupported')
		before = os.stat(path)
		check()
		if not stat.S_ISREG(before.st_mode):
			return ImageResult(message='Folder' if stat.S_ISDIR(before.st_mode) else 'Not a regular file', kind='error')
		with open(path, 'rb') as stream:
			prefix = stream.read(PROBE_LIMIT)
			check()
			if not known_text:
				from PyQt5.QtCore import QBuffer, QIODevice
				from PyQt5.QtGui import QImageReader
				device = QBuffer()
				device.setData(prefix)
				device.open(QIODevice.ReadOnly)
				try:
					reader = QImageReader(device)
					reader.setDecideFormatFromContent(True)
					image_format = bytes(reader.format())
				finally:
					device.close()
				if image_format:
					stream.close()
					return load_image(request, canceled, resolve)
			probe, _, _ = decode_text(prefix, len(prefix) >= before.st_size)
			if is_binary(probe):
				return ImageResult(message='Binary file', kind='unsupported')
			data = bytearray(prefix)
			while len(data) < min(before.st_size, READ_LIMIT):
				check()
				chunk = stream.read(min(65536, READ_LIMIT - len(data)))
				if not chunk:
					break
				data.extend(chunk)
		check()
		if _fingerprint(before) != _fingerprint(os.stat(path)):
			return ImageResult(message='File changed while loading', kind='error')
		truncated = before.st_size > READ_LIMIT
		text, encoding, warning = decode_text(bytes(data), not truncated)
		text = text.replace('\r\n', '\n').replace('\r', '\n')
		content = TextContent(text, path, encoding, _fingerprint(before), len(data), warning, truncated)
		result = convert_text(content, request.mode, request.colors, canceled)
		check()
		if _fingerprint(before) != _fingerprint(os.stat(path)):
			return ImageResult(message='File changed while loading', kind='error')
		return result
	except InterruptedError:
		return None
	except (OSError, ValueError) as error:
		return ImageResult(message='Cannot preview file: ' + str(error), kind='error')


class PreviewDocument(QTextDocument):
	def loadResource(self, resource_type, url):
		return QByteArray()


class PreviewBrowser(QTextBrowser):
	def loadResource(self, resource_type, url):
		return QByteArray()

	def mousePressEvent(self, event):
		self.parentWidget().source.setFocus(Qt.MouseFocusReason)
		self.setFocus(Qt.MouseFocusReason)
		super().mousePressEvent(event)

	def contextMenuEvent(self, event):
		menu = QMenu(self)
		copy = menu.addAction('Copy', self.copy)
		copy.setEnabled(self.textCursor().hasSelection())
		menu.addAction('Select all', self.selectAll)
		link = self.anchorAt(event.pos())
		if link:
			menu.addAction('Copy link address', lambda: QApplication.clipboard().setText(link))
		menu.exec_(event.globalPos())


class TextPreview(QWidget):
	mode_requested = pyqtSignal(str)
	changed = pyqtSignal()

	def __init__(self, source, parent):
		super().__init__(parent)
		self.source = source
		layout = QVBoxLayout(self)
		layout.setContentsMargins(0, 0, 0, 0)
		self.browser = PreviewBrowser(self)
		self.browser.setDocument(PreviewDocument(self.browser))
		self.browser.setReadOnly(True)
		self.browser.setUndoRedoEnabled(False)
		self.browser.setOpenLinks(False)
		self.browser.setOpenExternalLinks(False)
		self.browser.setAcceptDrops(False)
		self.browser.viewport().setAcceptDrops(False)
		self.browser.setAccessibleName('QuickView text')
		self.browser.installEventFilter(self)
		layout.addWidget(self.browser, 1)
		self.find_bar = QWidget(self)
		find_layout = QHBoxLayout(self.find_bar)
		find_layout.setContentsMargins(0, 0, 0, 0)
		self.find_input = QLineEdit(self.find_bar)
		self.find_input.setPlaceholderText('Find')
		self.find_input.setAccessibleName('Find in preview')
		self.find_input.installEventFilter(self)
		self.find_input.returnPressed.connect(self.find_next)
		find_layout.addWidget(self.find_input, 1)
		self.case_sensitive = QCheckBox('Match case', self.find_bar)
		self.case_sensitive.installEventFilter(self)
		find_layout.addWidget(self.case_sensitive)
		for label, icon, callback in (
			('Previous match', QStyle.SP_ArrowUp, lambda: self.find_next(True)),
			('Next match', QStyle.SP_ArrowDown, self.find_next),
			('Close Find', QStyle.SP_DialogCloseButton, self.close_find)
		):
			button = QToolButton(self.find_bar)
			button.setIcon(self.style().standardIcon(icon))
			button.setToolTip(label)
			button.setAccessibleName(label)
			button.setFocusPolicy(Qt.NoFocus)
			button.clicked.connect(lambda checked=False, action=callback: action())
			find_layout.addWidget(button)
		self.find_state = QLabel(self.find_bar)
		find_layout.addWidget(self.find_state)
		layout.addWidget(self.find_bar)
		self.find_bar.hide()
		controls = QHBoxLayout()
		self.mode_buttons = {}
		self.modes = QButtonGroup(self)
		for mode in ('rendered', 'source'):
			button = QToolButton(self)
			button.setText(mode.title())
			button.setCheckable(True)
			self.modes.addButton(button)
			button.setFocusPolicy(Qt.NoFocus)
			button.clicked.connect(lambda checked=False, value=mode: self.mode_requested.emit(value))
			self.mode_buttons[mode] = button
			controls.addWidget(button)
		self.metadata = QLabel(self)
		self.metadata.setTextFormat(Qt.PlainText)
		self.metadata.setWordWrap(True)
		controls.addWidget(self.metadata, 1)
		layout.addLayout(controls)

	def show_result(self, result):
		self.clear()
		formatted = bool(result.html)
		self.browser.setLineWrapMode(QTextBrowser.WidgetWidth if result.mode == 'rendered' and formatted else QTextBrowser.NoWrap)
		font = self.font() if result.mode == 'rendered' and formatted else QFontDatabase.systemFont(QFontDatabase.FixedFont)
		self.browser.document().setDefaultFont(font)
		if formatted:
			self.browser.setHtml(result.html)
		else:
			self.browser.setPlainText(result.content.text)
		self.browser.setTabStopDistance(QFontMetricsF(font).horizontalAdvance('    '))
		self.browser.moveCursor(QTextCursor.Start)
		can_format = not result.content.truncated and result.content.byte_count <= FORMAT_LIMIT
		self.modes.setExclusive(False)
		for mode, button in self.mode_buttons.items():
			button.setVisible(is_markdown(result.content.path))
			button.setEnabled(mode != 'rendered' or can_format)
			button.setChecked(mode == result.mode)
		self.modes.setExclusive(True)
		self.metadata.setText(' | '.join(value for value in (result.content.encoding, result.message) if value))
		self.changed.emit()

	def clear(self):
		self.browser.clear()
		self.find_bar.hide()
		self.find_input.clear()
		self.find_state.clear()
		self.metadata.clear()

	def close_find(self):
		self.find_bar.hide()
		self.browser.setFocus()

	def find_next(self, backwards=False):
		query = self.find_input.text()
		if not query:
			self.find_bar.show()
			self.find_input.setFocus()
			return
		flags = QTextDocument.FindFlags()
		if backwards:
			flags |= QTextDocument.FindBackward
		if self.case_sensitive.isChecked():
			flags |= QTextDocument.FindCaseSensitively
		cursor = self.browser.document().find(query, self.browser.textCursor(), flags)
		wrapped = cursor.isNull()
		if wrapped:
			start = self.browser.document().characterCount() - 1 if backwards else 0
			cursor = self.browser.document().find(query, start, flags)
		self.find_state.setText('Not found' if cursor.isNull() else 'Wrapped' if wrapped else '')
		if not cursor.isNull():
			self.browser.setTextCursor(cursor)
			self.browser.ensureCursorVisible()

	def eventFilter(self, watched, event):
		if event.type() == QEvent.ShortcutOverride:
			event.accept()
			return True
		if event.type() != QEvent.KeyPress:
			return False
		key, modifiers = event.key(), event.modifiers()
		if key in (Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Escape):
			if key == Qt.Key_Escape and self.find_bar.isVisible():
				self.close_find()
			else:
				self.source.setFocus()
		elif key == Qt.Key_F and modifiers == Qt.ControlModifier:
			self.find_bar.show()
			self.find_input.setFocus()
			self.find_input.selectAll()
		elif key == Qt.Key_F3 and modifiers in (Qt.NoModifier, Qt.ShiftModifier):
			self.find_next(modifiers == Qt.ShiftModifier)
		elif key in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr):
			return False
		elif key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down, Qt.Key_Home, Qt.Key_End, Qt.Key_PageUp, Qt.Key_PageDown) and not modifiers & (Qt.AltModifier | Qt.MetaModifier):
			return False
		elif key in (Qt.Key_A, Qt.Key_C) and modifiers == Qt.ControlModifier:
			return False
		elif watched is not self.browser and (
			(event.text() and event.text().isprintable() and modifiers in (
				Qt.NoModifier, Qt.ShiftModifier, Qt.ControlModifier | Qt.AltModifier)) or
			key in (Qt.Key_Backspace, Qt.Key_Delete, Qt.Key_Return, Qt.Key_Enter) or
			(modifiers == Qt.ControlModifier and key in (Qt.Key_X, Qt.Key_V, Qt.Key_Z, Qt.Key_Y))
		):
			return False
		else:
			self.source.setFocus()
			if self.source.hasFocus():
				self.source._controller.handle_shortcut(self.source, event)
		event.accept()
		return True