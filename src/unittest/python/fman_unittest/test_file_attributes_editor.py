from contextlib import contextmanager
from importlib import import_module
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import os
import sys


PLUGIN_ROOT = Path(__file__).resolve().parents[4] / 'plugins/FileAttributesEditor'


@contextmanager
def plugin_module():
	name = 'file_attributes_editor'
	spec = spec_from_file_location(name, PLUGIN_ROOT / name / '__init__.py',
		submodule_search_locations=[str(PLUGIN_ROOT / name)])
	module = module_from_spec(spec)
	sys.modules[name] = module
	try:
		spec.loader.exec_module(module)
		yield module, import_module(name + '.engine')
	finally:
		for key in tuple(sys.modules):
			if key == name or key.startswith(name + '.'):
				sys.modules.pop(key)


class _Stop(KeyboardInterrupt):
	pass


class FileAttributesEditorTest(TestCase):
	def setUp(self):
		context = plugin_module()
		self.plugin, self.engine = context.__enter__()
		self.addCleanup(context.__exit__, None, None, None)
		temporary = TemporaryDirectory()
		self.addCleanup(temporary.cleanup)
		self.root = Path(temporary.name).resolve()
		self.addCleanup(self._reset_attributes)
		for relative in ('a.txt', 'b.txt', 'sub/c.txt', 'sub/deep/d.txt', 'outside/o.txt'):
			path = self.root / relative
			path.parent.mkdir(parents=True, exist_ok=True)
			path.write_text(relative)
		import _winapi
		self.junction = self.root / 'sub/link'
		_winapi.CreateJunction(str(self.root / 'outside'), str(self.junction))
		self.addCleanup(lambda: self.junction.exists() and os.rmdir(self.junction))

	def _reset_attributes(self):
		for folder, names, files in os.walk(self.root):
			for name in names + files:
				path = os.path.join(folder, name)
				if not os.path.islink(path):
					self.engine.set_attributes(path, self.engine.NORMAL)

	def attributes(self, relative):
		return os.lstat(self.root / relative).st_file_attributes

	def operations(self, **arguments):
		writes, notified = [], []
		def write(path, attributes):
			writes.append((path, attributes))
		arguments.setdefault('write', write)
		arguments.setdefault('notify', notified.append)
		return self.engine.Operations(**arguments), writes, notified

	def test_starting_states_and_masks(self):
		engine = self.engine
		entries = [engine.Entry('x', engine.HIDDEN | engine.ARCHIVE, False), engine.Entry('y', engine.HIDDEN, True)]
		states = {start.id: (start.state, start.enabled) for start in engine.starting_states(entries)}
		self.assertEqual(('on', True), states['hidden'])
		self.assertEqual(('mixed', True), states['archive'])
		self.assertEqual(('off', True), states['readonly'])
		self.assertEqual(('off', False), states['temporary'])
		files = [engine.Entry('x', engine.TEMPORARY, False), engine.Entry('z', 0, False)]
		temporary = next(start for start in engine.starting_states(files) if start.id == 'temporary')
		self.assertEqual(('mixed', True), (temporary.state, temporary.enabled))
		self.assertEqual((engine.HIDDEN, engine.READONLY),
			engine.masks({'hidden': 'on', 'readonly': 'off', 'archive': 'mixed'}))

	def test_merge_preserves_unrelated_bits_and_skips_no_ops(self):
		engine = self.engine
		offline, reparse = 0x1000, 0x400
		entries = [engine.Entry('f', engine.ARCHIVE | offline | reparse, False),
			engine.Entry('g', engine.ARCHIVE, False), engine.Entry('h', engine.HIDDEN, False)]
		operations, writes, notified = self.operations()
		report = engine.Report()
		engine.apply(entries, engine.HIDDEN, engine.ARCHIVE, False, operations, report)
		self.assertEqual([('f', offline | engine.HIDDEN), ('g', engine.HIDDEN)], writes)
		self.assertEqual((2, 1), (report.changed, report.unchanged))
		operations, writes, notified = self.operations()
		engine.apply(entries[1:2], 0, engine.ARCHIVE, False, operations, engine.Report())
		self.assertEqual([('g', engine.NORMAL)], writes)

	def test_capture_rejects_links_unc_and_missing_items(self):
		engine = self.engine
		entries = engine.capture([str(self.root / 'a.txt'), str(self.root / 'sub')])
		self.assertEqual([False, True], [entry.is_dir for entry in entries])
		for path, message in ((self.junction, 'not links or junctions'),
				('\\\\server\\share\\x.txt', 'UNC'), (self.root / 'missing.txt', 'missing.txt')):
			with self.subTest(path=path), self.assertRaisesRegex(engine.Rejected, message):
				engine.capture([str(path)])
		link = self.root / 'symlink.txt'
		try:
			os.symlink(self.root / 'a.txt', link)
		except OSError:
			self.skipTest('Creating symbolic links needs Developer Mode or the privilege.')
		with self.assertRaisesRegex(engine.Rejected, 'not links or junctions'):
			engine.capture([str(link)])

	def test_apply_on_disk_recursively_skips_junctions_and_announces_folders(self):
		engine = self.engine
		entries = engine.capture([str(self.root / 'a.txt')])
		operations, writes, notified = self.operations(write=engine.set_attributes)
		engine.apply(entries, engine.HIDDEN, 0, False, operations, engine.Report())
		self.assertTrue(self.attributes('a.txt') & engine.HIDDEN)
		self.assertFalse(self.attributes('b.txt') & engine.HIDDEN)
		self.assertEqual([str(self.root)], notified)
		archive = self.attributes('sub/deep/d.txt') & engine.ARCHIVE
		entries = engine.capture([str(self.root / 'sub')])
		operations, writes, notified = self.operations(write=engine.set_attributes)
		report = engine.Report()
		engine.apply(entries, engine.HIDDEN, 0, True, operations, report)
		for relative in ('sub', 'sub/c.txt', 'sub/deep', 'sub/deep/d.txt'):
			self.assertTrue(self.attributes(relative) & engine.HIDDEN, relative)
		self.assertEqual(archive, self.attributes('sub/deep/d.txt') & engine.ARCHIVE)
		self.assertFalse(self.attributes('outside/o.txt') & engine.HIDDEN)
		self.assertFalse(self.attributes('sub/link') & engine.HIDDEN)
		self.assertEqual((4, 1, 0), (report.changed, report.skipped, report.failed))
		self.assertEqual(sorted(map(str, (self.root, self.root / 'sub', self.root / 'sub/deep'))), sorted(notified))

	def test_static_model_does_not_reread_chosen_items(self):
		engine = self.engine
		entries = engine.capture([str(self.root / 'a.txt')])
		operations, writes, notified = self.operations()
		with patch.object(engine.os, 'lstat', side_effect=AssertionError('re-read')):
			engine.apply(entries, engine.HIDDEN, 0, False, operations, engine.Report())
		self.assertEqual([(str(self.root / 'a.txt'), (entries[0].attributes & engine.SETTABLE) | engine.HIDDEN)], writes)

	def test_denied_writes_are_reported_and_the_walk_continues(self):
		engine = self.engine
		sub = str(self.root / 'sub')
		def write(path, attributes):
			if path == sub:
				raise PermissionError(5, 'Access is denied', path)
			engine.set_attributes(path, attributes)
		operations, writes, notified = self.operations(write=write)
		report = engine.Report()
		engine.apply(engine.capture([sub]), engine.HIDDEN, 0, True, operations, report)
		self.assertEqual((1, 3), (report.failed, report.changed))
		self.assertEqual(sub, report.failures[0][0])
		self.assertTrue(self.attributes('sub/c.txt') & engine.HIDDEN)

	def test_failures_are_bounded(self):
		engine = self.engine
		report = engine.Report()
		for index in range(engine.MAX_FAILURES + 500):
			report.fail('C:\\\u00e9' * 2000 + str(index), OSError('\u05e9' * 1000))
		self.assertEqual((engine.MAX_FAILURES + 500, engine.MAX_FAILURES), (report.failed, len(report.failures)))
		path, error = report.failures[-1]
		self.assertLessEqual(len(path), engine.MAX_PATH_TEXT)
		self.assertIn('\u2026', path)
		self.assertLessEqual(len(error), engine.MAX_ERROR_TEXT)

	def test_cancellation_announces_committed_writes_only(self):
		engine = self.engine
		for limit, expected in ((1, []), (4, [str(self.root / 'sub')])):
			calls = []
			def check():
				calls.append(None)
				if len(calls) >= limit:
					raise _Stop()
			operations, writes, notified = self.operations(check=check)
			report = engine.Report()
			with self.subTest(limit=limit), self.assertRaises(_Stop):
				engine.apply(engine.capture([str(self.root / 'sub')]), engine.HIDDEN, 0, True, operations, report)
			self.assertEqual(expected, notified[:1] if expected else notified)
			self.assertEqual(len(writes), report.changed)
		def failing(folder):
			raise RuntimeError('observer')
		operations, writes, notified = self.operations(notify=failing)
		report = engine.Report()
		engine.apply(engine.capture([str(self.root / 'a.txt')]), engine.HIDDEN, 0, False, operations, report)
		self.assertEqual((1, 0), (report.changed, report.failed))

	def command(self, chosen, result):
		from fman.ui import CheckListResult
		from fman.url import as_url
		pane = Mock()
		pane.get_path.return_value = as_url(self.root)
		pane.get_selected_files.return_value = [as_url(self.root / name) for name in chosen]
		pane.get_file_under_cursor.return_value = None
		with patch('fman.submit_task', side_effect=lambda task: task()) as submit, \
				patch('fman.ui.show_quick_check_list', return_value=CheckListResult(*result)) as dialog, \
				patch('fman.show_status_message') as status, patch('fman.show_alert') as alert, \
				patch('fman.ui.show_quick_table') as table, patch('fman.fs.notify_file_changed') as notify:
			self.plugin.EditAttributes(pane)()
		return Mock(submit=submit, dialog=dialog, status=status, alert=alert, table=table, notify=notify)

	def test_command_does_nothing_without_changes(self):
		for approval in ('primary', 'alternate', None):
			with self.subTest(approval=approval):
				calls = self.command(('a.txt', 'sub'), ({}, approval))
				self.assertEqual(1, calls.submit.call_count)
				calls.notify.assert_not_called()
				if approval:
					calls.status.assert_called_once_with('No attributes changed.', timeout_secs=5)
				else:
					calls.status.assert_not_called()
		self.assertFalse(self.attributes('a.txt') & self.engine.HIDDEN)

	def test_command_applies_choice_and_publishes(self):
		from fman.url import as_url
		calls = self.command(('a.txt', 'sub'), ({'hidden': 'on'}, 'primary'))
		arguments = calls.dialog.call_args.kwargs
		self.assertEqual(('checkbox3', True, 'Attributes: 2 items (1 folder)'),
			(arguments['states'], arguments['alternate'], arguments['title']))
		self.assertIn('Shift+Enter: Apply recursively', arguments['status'])
		temporary = next(item for item in arguments['items'] if item.id == 'temporary')
		self.assertFalse(temporary.enabled)
		self.assertTrue(self.attributes('a.txt') & self.engine.HIDDEN)
		self.assertTrue(self.attributes('sub') & self.engine.HIDDEN)
		self.assertFalse(self.attributes('sub/c.txt') & self.engine.HIDDEN)
		calls.notify.assert_called_once_with(as_url(self.root))
		self.assertIn('2 changed', calls.status.call_args.args[0])
		calls.table.assert_not_called()
		calls = self.command(('sub',), ({'hidden': 'on'}, 'alternate'))
		self.assertTrue(self.attributes('sub/deep/d.txt') & self.engine.HIDDEN)

	def test_command_rejects_links_before_the_dialog(self):
		calls = self.command(('sub/link',), ({'hidden': 'on'}, 'primary'))
		calls.dialog.assert_not_called()
		self.assertIn('not links or junctions', calls.alert.call_args.args[0])

	def test_command_without_chosen_items_returns_cleanly(self):
		# A key binding or direct call can run the command in an empty folder.
		calls = self.command((), ({'hidden': 'on'}, 'primary'))
		calls.submit.assert_not_called()
		calls.dialog.assert_not_called()
		calls.alert.assert_not_called()
		calls.status.assert_called_once_with('Edit attributes: no files selected.', timeout_secs=5)

	def test_publication_refreshes_cached_local_metadata(self):
		from core.fs.local import LocalFileSystem
		from fman.impl.plugins.mother_fs import MotherFileSystem
		from fman.url import as_url
		engine = self.engine
		mother = MotherFileSystem()
		mother.add_child('file://', LocalFileSystem())
		def hidden(relative):
			return bool(mother.query(as_url(self.root / relative), 'stat').st_file_attributes & engine.HIDDEN)
		# Cache every queried item first; no pane observes the folders.
		self.assertEqual([False] * 4, [hidden(relative) for relative in ('a.txt', 'sub', 'sub/c.txt', 'sub/deep/d.txt')])
		calls = []
		def check():
			calls.append(None)
			if len(calls) >= 4:
				raise _Stop()
		with patch('fman.fs._get_mother_fs', return_value=mother):
			operations = engine.Operations(notify=self.plugin._notify)
			engine.apply(engine.capture([str(self.root / 'a.txt')]), engine.HIDDEN, 0, False, operations, engine.Report())
			self.assertTrue(hidden('a.txt'))
			# Cancelled before sub/deep/d.txt: committed writes are still published.
			operations = engine.Operations(notify=self.plugin._notify, check=check)
			with self.assertRaises(_Stop):
				engine.apply(engine.capture([str(self.root / 'sub')]), engine.HIDDEN, 0, True, operations, engine.Report())
		self.assertEqual([True, True, False], [hidden(relative) for relative in ('sub', 'sub/c.txt', 'sub/deep/d.txt')])

	def test_plugin_uses_public_apis_only(self):
		for path in (PLUGIN_ROOT / 'file_attributes_editor').glob('*.py'):
			source = path.read_text(encoding='utf-8')
			for forbidden in ('PyQt', 'fman.impl', 'import core', 'from core'):
				self.assertNotIn(forbidden, source, path.name)

	def test_file_context_menu_adds_edit_attributes_after_properties(self):
		import yaml
		from fman import DirectoryPane, DirectoryPaneCommand
		from fman.impl.plugins.command_registry import ApplicationCommandRegistry, PaneCommandRegistry
		from fman.impl.plugins.context_menu import ContextMenuProvider
		from fman.impl.plugins.key_bindings import KeyBindings
		from fman.impl.plugins.plugin import _get_command_name
		from fman.url import as_url
		class ShowExplorerProperties(DirectoryPaneCommand):
			def __call__(self):
				pass
		self.assertEqual(('Edit attributes',), self.plugin.EditAttributes.aliases)
		registry = PaneCommandRegistry(None, None)
		for command in (ShowExplorerProperties, self.plugin.EditAttributes):
			registry.register_command(_get_command_name(command), command)
		provider = ContextMenuProvider(registry, ApplicationCommandRegistry(None, None, None), KeyBindings())
		core = PLUGIN_ROOT.parents[1] / 'src/main/resources/base/Plugins/Core/File Context Menu.yaml'
		entries = yaml.safe_load(core.read_text(encoding='utf-8'))
		self.assertEqual([], provider.load([entry for entry in entries if entry.get('id') == 'properties'
			or entry.get('command') in registry.get_commands()], '', provider.FILE_CONTEXT))
		plugin = yaml.safe_load((PLUGIN_ROOT / 'File Context Menu.yaml').read_text(encoding='utf-8'))
		self.assertEqual([], provider.load(plugin, '', provider.FILE_CONTEXT))
		url = as_url(self.root / 'a.txt')
		for location, expected in ((as_url(self.root), ['P&roperties', 'Edit &attributes...']),
				('zip://C:/archive.zip', ['P&roperties'])):
			with self.subTest(location=location):
				widget = Mock()
				widget.get_location.return_value = location
				widget.get_selected_files.return_value = []
				widget.get_file_under_cursor.return_value = url
				pane = DirectoryPane(None, widget, registry)
				self.assertEqual(expected, [entry[0] for entry in provider.get_context_menu(pane, url)])
