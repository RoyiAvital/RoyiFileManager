"""The About window: product metadata from AppMeta.json, the icon and the Zen."""

from html import escape

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QVBoxLayout

ICON_SIZE = 96
ZEN = (
	'Looks matter',
	'Speed counts',
	'Extending must be easy',
	'Customisability is important',
	'But not at the expense of speed',
	'I/O is better asynchronous',
	"Don't reinvent the wheel",
)


def _link(url):
	return '<a href="%s">%s</a>' % (escape(url), escape(url.split('://', 1)[-1]))


class AboutWindow(QDialog):
	"""Frameless; Esc, Enter or clicking elsewhere closes it."""

	def __init__(self, name, metadata, icon_path, parent=None):
		super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
		self.setObjectName('about')
		self.setAttribute(Qt.WA_DeleteOnClose)
		self.setWindowTitle('About ' + name)
		icon = QLabel(self)
		icon.setPixmap(QIcon(icon_path).pixmap(ICON_SIZE, ICON_SIZE))
		icon.setAlignment(Qt.AlignTop)
		title = QLabel(name, self)
		font = QFont(title.font())
		font.setPointSizeF(font.pointSizeF() * 1.8)
		font.setBold(True)
		title.setFont(font)
		version = QLabel('Version ' + str(metadata.get('version', '')), self)
		version.setObjectName('about-version')
		description = QLabel(str(metadata.get('description', '')), self)
		description.setWordWrap(True)
		rows = [('Project', metadata.get('project_link')), ('Documentation', metadata.get('documentation_link'))]
		links = QLabel('<br>'.join('%s: %s' % (label, _link(url)) for label, url in rows if url), self)
		links.setTextFormat(Qt.RichText)
		links.setOpenExternalLinks(True)
		separator = QFrame(self)
		separator.setObjectName('about-separator')
		separator.setFrameShape(QFrame.HLine)
		zen_title = QLabel('The Zen of ' + name, self)
		bold = QFont(zen_title.font())
		bold.setBold(True)
		zen_title.setFont(bold)
		zen = QLabel('\n'.join(ZEN), self)
		zen.setObjectName('about-zen')
		hint = QLabel('Esc to close', self)
		hint.setObjectName('about-hint')
		hint.setAlignment(Qt.AlignRight)
		text = QVBoxLayout()
		text.setSpacing(6)
		for widget in (title, version, description, links, separator, zen_title, zen, hint):
			text.addWidget(widget)
		layout = QHBoxLayout(self)
		layout.setContentsMargins(24, 24, 24, 16)
		layout.setSpacing(24)
		layout.addWidget(icon)
		layout.addLayout(text)
		self.setFixedWidth(560)

	def show_centered(self):
		self.adjustSize()
		parent = self.parentWidget()
		if parent is not None:
			center = parent.frameGeometry().center()
			self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)
		self.show()
		self.activateWindow()

	def keyPressEvent(self, event):
		if event.key() in (Qt.Key_Return, Qt.Key_Enter):
			self.close()
		else:
			super().keyPressEvent(event)

	def changeEvent(self, event):
		super().changeEvent(event)
		if event.type() == event.ActivationChange and self.isVisible() and not self.isActiveWindow():
			self.close()
