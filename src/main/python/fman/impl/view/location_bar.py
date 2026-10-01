from fman.impl.util.qt import ClickFocus
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QLineEdit

class LocationBar(QLineEdit):

	clicked = pyqtSignal()

	def __init__(self, parent=None):
		super().__init__(parent)
		self.setFocusPolicy(ClickFocus)
		self.setReadOnly(True)
	def mousePressEvent(self, e):
		super().mousePressEvent(e)
		self.clicked.emit()
