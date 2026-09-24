from collections import defaultdict
from os.path import basename, dirname
from PyQt5.QtGui import QFontDatabase
from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, \
	QHeaderView, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout

import json


def collect_shortcuts(paths, available_commands=None):
	result = []
	occupied = set()
	for path in reversed(paths):
		try:
			with open(path, 'r') as file:
				bindings = json.load(file)
		except (FileNotFoundError, OSError, ValueError):
			continue
		if not isinstance(bindings, list):
			continue
		plugin_name = basename(dirname(path))
		for binding in bindings:
			try:
				command = binding['command']
				shortcut = binding['keys'][0]
			except (KeyError, IndexError, TypeError):
				continue
			if not isinstance(command, str) or not isinstance(shortcut, str):
				continue
			if available_commands is not None and command not in available_commands:
				continue
			if shortcut not in occupied:
				result.append((plugin_name, command, shortcut))
			occupied.add(shortcut)
	return result


class ShortcutsDialog(QDialog):
	def __init__(self, parent, shortcuts, get_command_title):
		super().__init__(parent)
		self.setObjectName('shortcuts-dialog')
		self.setWindowTitle('Keyboard shortcuts')
		self.resize(760, 560)
		self.setMinimumSize(560, 400)
		self._trees = []

		title = QLabel('Keyboard shortcuts')
		title.setObjectName('shortcuts-title')
		description = QLabel(
			'Search active shortcuts. Use Ctrl+Shift+P to run any command.'
		)
		description.setObjectName('shortcuts-description')
		self._search = QLineEdit()
		self._search.setPlaceholderText('Search commands or shortcuts')
		self._search.setClearButtonEnabled(True)
		self._search.textChanged.connect(self._filter)

		built_in = []
		plugins = defaultdict(list)
		for plugin_name, command, shortcut in shortcuts:
			entry = get_command_title(command), shortcut
			if plugin_name == 'Core':
				built_in.append(entry)
			else:
				plugins[_display_plugin_name(plugin_name)].append(entry)

		tabs = QTabWidget()
		tabs.addTab(self._create_tree(built_in), 'Built-in (%d)' % len(built_in))
		plugin_count = sum(map(len, plugins.values()))
		tabs.addTab(
			self._create_tree([], plugins), 'Plug-ins (%d)' % plugin_count
		)

		buttons = QDialogButtonBox(QDialogButtonBox.Close)
		buttons.rejected.connect(self.reject)
		buttons.accepted.connect(self.accept)
		layout = QVBoxLayout(self)
		layout.setContentsMargins(22, 18, 22, 18)
		layout.setSpacing(10)
		layout.addWidget(title)
		layout.addWidget(description)
		layout.addWidget(self._search)
		layout.addWidget(tabs, 1)
		layout.addWidget(buttons)

	def _create_tree(self, entries, groups=None):
		tree = QTreeWidget()
		tree.setObjectName('shortcuts-tree')
		tree.setRootIsDecorated(bool(groups))
		tree.setAlternatingRowColors(True)
		tree.setUniformRowHeights(True)
		tree.setHeaderLabels(('Command', 'Shortcut'))
		tree.header().setStretchLastSection(False)
		tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
		tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
		if groups:
			for group_name in sorted(groups, key=str.casefold):
				group = QTreeWidgetItem(tree, (group_name, ''))
				group.setFirstColumnSpanned(True)
				font = group.font(0)
				font.setBold(True)
				group.setFont(0, font)
				self._add_entries(group, groups[group_name])
				group.setExpanded(True)
		else:
			self._add_entries(tree, entries)
		self._trees.append(tree)
		return tree

	@staticmethod
	def _add_entries(parent, entries):
		shortcut_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
		for command, shortcut in sorted(entries, key=lambda row: row[0].casefold()):
			item = QTreeWidgetItem(parent, (command, shortcut))
			item.setFont(1, shortcut_font)

	def _filter(self, query):
		query = query.casefold().strip()
		for tree in self._trees:
			for index in range(tree.topLevelItemCount()):
				item = tree.topLevelItem(index)
				if item.childCount():
					visible_children = False
					for child_index in range(item.childCount()):
						child = item.child(child_index)
						visible = _matches(child, query) or query in item.text(0).casefold()
						child.setHidden(not visible)
						visible_children = visible_children or visible
					item.setHidden(not visible_children)
				else:
					item.setHidden(not _matches(item, query))


def _matches(item, query):
	return not query or any(query in item.text(column).casefold() for column in (0, 1))


def _display_plugin_name(plugin_name):
	if plugin_name == 'Settings':
		return 'Custom shortcuts'
	return plugin_name