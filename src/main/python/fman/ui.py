"""Provisional RoyiFileManager UI extension, separate from the fman 1.7.5 API.

Commands call UiController.show(); the host constructs widgets on the Qt thread
and invokes UiController.build(window, pane), the canonical UI construction hook.
Keep plug-in state and actions in plain Python objects rather than subclassing
the host window; connect its shown(query), busy_changed(busy) and disposed
notifications. Qt widget components belong to this opt-in module, not the general
DirectoryPane/Window API. Breaking extension changes require changelog
migration notes. JsonSettings uses bounded workers and plug-in-specific JSON.
"""

from fman.impl.ui import ListItem, Resource, UiController, UiOwner, matchers
from fman.impl.ui import resource as settings_resource
from fman.impl.ui.quicklist import QuickList
from fman.impl.ui.panel import Panel, DropDown, IconButton, JsonSettings, TextButton
from fman.impl.ui.session import NavigationHandle, PaneToolWindow, ToolWindow, navigate


__all__ = [
	'ListItem', 'QuickList', 'Panel', 'IconButton', 'TextButton',
	'DropDown', 'JsonSettings', 'UiController', 'UiOwner', 'Resource',
	'settings_resource', 'matchers', 'ToolWindow', 'PaneToolWindow',
	'NavigationHandle', 'navigate'
]