"""Provisional RoyiFileManager UI extension, separate from the fman 1.7.5 API.

Use the Qt-free services: show_quick_list to select items (an on_open handle lets
a driver such as a Panel read the state and replace the items), show_panel with
plain descriptors and handles, and the blocking show_quick_table for narrowing
static results. show_quick_board composes one string with a caller-driven typed
preview. UiController.build(window, pane), ToolWindow, PaneToolWindow and
OutputTextBox remain Qt-based until a Qt-free replacement exists. Breaking
extension changes require changelog migration notes.
"""

from fman.impl.ui import ListItem, Resource, UiController, UiOwner, matchers
from fman.impl.ui import resource as settings_resource
from fman.impl.ui.output import OutputTextBox
from fman.impl.ui.session import NavigationHandle, PaneToolWindow, ToolWindow, navigate
from fman.impl.ui.table_data import Action, Choice, DateField, IntegerField, Label, Select, Separator, QuickTableColumn, QuickTableRow, TextField, Toggle
from fman.impl.ui.facade import PanelHandle, show_panel, show_quick_table
from fman.impl.ui.quick_list_data import QuickListState
from fman.impl.ui.quick_list_window import QuickListHandle, show_quick_list
from fman.impl.ui.quick_board import show_quick_board


__all__ = [
	'ListItem', 'UiController', 'UiOwner', 'Resource',
	'settings_resource', 'matchers', 'ToolWindow', 'PaneToolWindow',
	'NavigationHandle', 'navigate', 'OutputTextBox', 'QuickTableRow', 'QuickTableColumn',
	'TextField', 'Toggle', 'Choice', 'Label', 'Action', 'PanelHandle',
	'Select', 'DateField', 'IntegerField', 'Separator',
	'show_quick_table', 'show_panel', 'show_quick_list', 'QuickListHandle', 'QuickListState',
	'show_quick_board'
]