from fman.impl.util.qt import MoveAction, NoButton, \
	ControlModifier, CopyAction, from_qurl
from fman.url import as_human_readable, splitscheme
from ntpath import splitdrive
from PyQt5.QtCore import Qt, QItemSelectionModel as QISM
from PyQt5.QtWidgets import QTableView, QAbstractItemView

class DragAndDrop(QTableView):

	_IDLE_STATES = (QAbstractItemView.NoState, QAbstractItemView.AnimatingState)

	def __init__(self, parent=None):
		super().__init__(parent)
		self._dragged_index = None
		self.setDragEnabled(True)
		self.setDragDropMode(self.DragDrop)
		self.setDefaultDropAction(MoveAction)
		self.setDropIndicatorShown(True)
		self.setAcceptDrops(True)
		# Consider:
		#   A/
		#   B/
		# Drag A/ downwards. With dragDropOverwriteMode = False, as you leave A/
		# but before you reach B/, Qt draws a horizontal line between A/ and B/,
		# presumably to let you drag items to between rows. This may make sense
		# for other widgets, but we don't want it. We therefore set
		# dragDropOverwriteMode to True:
		self.setDragDropOverwriteMode(True)
	def mouseMoveEvent(self, event):
		if event.buttons() != NoButton and self.state() in self._IDLE_STATES:
			self._dragged_index = self.indexAt(event.pos())
			if self._dragged_index.isValid():
				# Qt's default implementation only starts dragging when there
				# are selected items. We also want to start dragging when there
				# aren't (because in this case we drag the focus item):
				self.setState(self.DraggingState)
				# startDrag(...) below now initiates drag and drop.
				return
		else:
			super().mouseMoveEvent(event)
	def startDrag(self, supportedActions):
		if not self._dragged_index or not self._dragged_index.isValid():
			return
		if self._dragged_index in self.selectedIndexes():
			super().startDrag(supportedActions)
		else:
			# The default implementation of Qt only supports dragging the
			# currently selected item(s). We therefore briefly need to "select"
			# the items we wish to drag. This has the (unintended) side-effect
			# that the dragged items are also rendered as being selected.
			selection = self.selectionModel().selection()
			current = self.selectionModel().currentIndex()
			generation = getattr(self, '_view_generation', None)
			try:
				self.selectionModel().clear()
				# When dragging items that have actually been selected by the
				# user, the cursor is on one of the selected items (because the
				# user clicked on it when initiating the drag). Mimic the same
				# behaviour for consistency:
				self.setCurrentIndex(self._dragged_index)
				self.selectionModel().select(
					self._dragged_index, QISM.ClearAndSelect | QISM.Rows
				)
				super().startDrag(supportedActions)
			finally:
				if generation == getattr(self, '_view_generation', None):
					self.selectionModel().select(selection, QISM.ClearAndSelect)
					self.selectionModel().setCurrentIndex(current, QISM.NoUpdate)
	def dragMoveEvent(self, event):
		super().dragMoveEvent(event)
		if event.isAccepted():
			event.setDropAction(self._drop_action(event))
			event.accept()
	def dropEvent(self, event):
		action = self._drop_action(event)
		event.setDropAction(action)
		super().dropEvent(event)
		if action == MoveAction:
			# If we accept the event (which super().dropEvent(...) does above),
			# then Windows moves the file to the Recycle Bin!!! Avoid this:
			event.ignore()
	def _drop_action(self, event):
		"""Like Explorer: Ctrl copies, Shift moves, otherwise copy across volumes and move within one."""
		modifiers = event.keyboardModifiers()
		if modifiers & ControlModifier:
			return CopyAction
		if modifiers & Qt.ShiftModifier:
			return MoveAction
		destination = _volume(self.model().get_location())
		sources = [_volume(qurl) for qurl in event.mimeData().urls()]
		if destination is not None and any(source != destination for source in sources):
			return CopyAction
		return MoveAction

def _volume(url):
	"""The drive (`c:`) or UNC share of a local file URL or QUrl; None otherwise."""
	try:
		if not isinstance(url, str):
			url = from_qurl(url)
		if splitscheme(url)[0] != 'file://':
			return None
	except ValueError:
		return None
	return splitdrive(as_human_readable(url))[0].casefold()