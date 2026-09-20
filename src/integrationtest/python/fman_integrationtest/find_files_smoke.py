import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
import traceback


def exercise(context, root, output):
	from fman.impl.ui.facade import _hosts
	from fman.impl.util.qt.thread import run_in_main_thread
	from fman.url import as_url
	from find_files import FindUI
	from PyQt5.QtCore import QPoint, Qt, QTimer
	from PyQt5.QtGui import QIcon
	from PyQt5.QtTest import QTest
	from PyQt5.QtWidgets import QApplication
	gui = lambda function: run_in_main_thread(function)()
	def action_appearance(host):
		buttons = [host.controls[name][1] for name in ('search', 'stop')]
		return (tuple((button.size(), button.iconSize(), button.autoRaise(), button.toolTip(), button.isEnabled(),
			button.icon().pixmap(16, 16, QIcon.Normal if button.isEnabled() else QIcon.Disabled).toImage()) for button in buttons),
			buttons[1].mapTo(host.form, QPoint()).x() - buttons[0].mapTo(host.form, QPoint(buttons[0].width(), 0)).x())
	def wait_for(predicate, message):
		ready = Event()
		def connect():
			timer = QTimer(context.main_window)
			timer.setInterval(10)
			def check():
				if predicate():
					timer.stop()
					timer.deleteLater()
					ready.set()
			timer.timeout.connect(check)
			timer.start()
			check()
		gui(connect)
		assert ready.wait(15), message
	code = 1
	try:
		wait_for(lambda: len(context.window.get_panes()) == 2 and all(pane.get_path() == as_url(root) for pane in context.window.get_panes()), 'Startup panes did not restore')
		pane = context.window.get_panes()[0]
		assert pane.get_command_aliases('find_files')[0] == 'Find files with fd'
		bindings = context.key_bindings.get_sanitized_bindings()
		assert next(binding for binding in bindings if binding['keys'] == ['Shift+F7'])['command'] == 'find_files'
		pane.run_command('find_files')
		wait_for(lambda: any(host.owner is FindUI.owner for host in _hosts.values()), 'Find Files panel did not open')
		host = gui(lambda: next(host for host in _hosts.values() if host.owner is FindUI.owner))
		session = host.on_action.__self__
		def geometry():
			main = context.main_window
			main.activateWindow()
			for width in (960, 1280, 1440):
				if width > main.screen().availableGeometry().width():
					print('SKIP native width exceeding available screen:', width, flush=True)
					continue
				main.resize(width, 600)
				QApplication.processEvents()
				assert main.width() == width, 'Dock prevented requested window width'
				for body, actions in host.form.rows:
					layout = body.layout()
					rects = [layout.itemAt(index).geometry() for index in range(layout.count())]
					for index, rect in enumerate(rects):
						assert body.rect().contains(rect), 'Clipped control group'
						assert not any(rect.intersects(other) for other in rects[index + 1:]), 'Overlapping groups'
				for record, wrapper, label in host.form.fields:
					assert label.width() >= label.fontMetrics().horizontalAdvance(label.text()), 'Clipped field label'
				for name in ('modified_label', 'size_label', 'root'):
					label = host.controls[name][1]
					assert label.width() > 20 and label.text(), 'Missing group/root label'
					assert label.isVisible() and label.parentWidget().rect().contains(label.geometry()), 'Clipped section label: ' + name
					if name != 'root':
						assert label.text() == label.content, 'Elided section label: ' + name
				for name in ('min_size', 'max_size'):
					bound, unit = host.controls[name][1], host.controls[name + '_unit'][1]
					assert bound.mapTo(host.form, QPoint()).y() == unit.parentWidget().mapTo(host.form, QPoint()).y(), 'Unit separated from bound'
				for name in ('pattern', 'extensions', 'exclude', 'type', 'case_mode', 'recursive', 'search'):
					assert host.controls[name][1].height() == 28, 'Unequal control height: ' + name
				for name in ('min_size', 'max_size', 'start_date', 'end_date', 'max_results'):
					assert host.controls[name][1].editor.height() == 28, 'Unequal field height: ' + name
				assert 'max_depth' not in host.controls
				assert session.panel.snapshot()['max_results'] is None
				limit = host.controls['max_results'][1]
				assert host.form.rows[1][0].isAncestorOf(limit), 'Max Results is not in row two'
				if width >= 1280:
					assert limit.mapTo(host.form, QPoint()).y() == host.controls['start_date'][1].mapTo(host.form, QPoint()).y(), 'Row two unexpectedly wrapped'
				stop = host.controls['stop'][1]
				previous_right = max(body.layout().itemAt(index).geometry().right() + 1
					for body, actions in host.form.rows[:2] for index in range(body.layout().count()))
				assert stop.mapTo(host.form, QPoint(stop.width(), 0)).x() == previous_right, 'Toolbar does not align with rows above'
				for button, name in host.icon_controls:
					image = button.icon().pixmap(16, 16).toImage()
					assert any(image.pixelColor(horizontal, vertical).alpha() for horizontal in range(image.width()) for vertical in range(image.height())), 'Blank icon: ' + name
				assert main._splitter.height() > 150, 'Dock consumed pane area'
				assert main._panel_dock.grab().save(str(output.with_name(output.stem + '-panel-%d.png' % width)))
				print('Native panel:', width, main._panel_dock.height(), 'DPR', main.devicePixelRatioF(), flush=True)
			main.resize(960, 600)
			stops = [control for control in host.form.tab_controls if control.isEnabled()]
			stops.append(main._panel_dock.close_button)
			for sequence, modifiers in ((stops, Qt.NoModifier), (list(reversed(stops)), Qt.ShiftModifier)):
				sequence[0].setFocus()
				for current, expected in zip(sequence, sequence[1:]):
					QTest.keyClick(current, Qt.Key_Tab, modifiers)
					assert QApplication.focusWidget() is expected, 'Tab missed ' + expected.accessibleName()
			return action_appearance(host)
		find_actions = gui(geometry)
		gui(lambda: host.controls['case_mode'][1].set_value('sensitive'))
		gui(lambda: host.controls['hidden'][1].click())
		wait_for(lambda: not session.saving, 'Preferences did not settle')
		settings = root / 'UserSettings/Plugins/User/Settings/FindFiles (Windows).json'
		saved = json.loads(settings.read_text(encoding='utf-8'))
		assert saved['case_mode'] == 'sensitive' and saved['hidden']
		assert not {'pattern', 'max_results', 'start_date', 'min_size'} & saved.keys()
		gui(lambda: session.panel.update(values={'pattern': '*.txt', 'max_results': None}))
		gui(lambda: session.action('search', session.panel.snapshot()))
		wait_for(lambda: session.runner is None and session.table is not None, 'Search did not finish')
		window = gui(lambda: host.table_window)
		wait_for(window.isVisible, 'Results were not presented')
		assert gui(window.windowTitle) == 'Find files'
		assert gui(lambda: window.table.counts.text()) == 'Showing 2 / 2 entries'
		gui(lambda: setattr(session.table, 'filter_text', 'report'))
		wait_for(lambda: window.table.counts.text() == 'Showing 1 / 2 entries', 'Filtered counter did not update')
		gui(lambda: window.grab().save(str(output)))
		table = session.table
		gui(lambda: window.activate_cell(*table.current_cell))
		wait_for(lambda: not table.is_open, 'Navigation did not close results')
		wait_for(lambda: pane.get_file_under_cursor() == as_url(root / 'nested/report.txt'), 'Result was not highlighted')
		assert session.root == str(root / 'nested')
		session.panel.close()
		pane.run_command('find_files')
		wait_for(lambda: any(host.owner is FindUI.owner for host in _hosts.values()), 'Panel did not reopen')
		reopened = gui(lambda: next(host for host in _hosts.values() if host.owner is FindUI.owner)).on_action.__self__
		assert reopened.panel.snapshot()['case_mode'] == 'sensitive'
		assert reopened.panel.snapshot()['max_results'] is None
		assert reopened.panel.snapshot()['pattern'] == ''
		reopened.panel.close()
		pane.run_command('search_files')
		from search_files import SearchUI
		wait_for(lambda: any(host.owner is SearchUI.owner for host in _hosts.values()), 'Reference Search Files panel did not open')
		def reference_panel():
			context.main_window.resize(1280, 600)
			QApplication.processEvents()
			reference = next(host for host in _hosts.values() if host.owner is SearchUI.owner)
			assert action_appearance(reference) == find_actions, 'Find Files actions differ from Search Files'
			context.main_window._panel_dock.grab().save(str(output.with_name(output.stem + '-search-files-reference.png')))
			print('Reference Search Files height:', context.main_window._panel_dock.height(), flush=True)
		gui(reference_panel)
		gui(lambda: next(host for host in _hosts.values() if host.owner is SearchUI.owner).close())
		print('PASS: native startup, registration, Shift+F7, layout, persistence, counts and navigation', flush=True)
		code = 0
	except BaseException:
		traceback.print_exc()
	finally:
		FindUI.owner.invalidate()
		def stop_models():
			models = [pane._widget._model.sourceModel() for pane in context.window.get_panes()]
			for model in models:
				model.shutdown()
			return models
		for model in gui(stop_models):
			model._worker._thread.join(5)
			if model._worker._thread.is_alive():
				code = 1
		gui(lambda: context.app.exit(code))


def main():
	isolated = '--isolated-plugins' in sys.argv
	with TemporaryDirectory(prefix='find-files-smoke-') as temporary:
		root = Path(temporary)
		(root / 'nested').mkdir()
		(root / 'nested/report.txt').write_bytes(b'report')
		(root / 'other.txt').write_bytes(b'')
		os.environ['ROYIFILEMANAGER_USER_SETTINGS'] = str(root / 'UserSettings')
		from fman.impl.application_context import get_application_context
		from PyQt5.QtCore import QTimer
		context = get_application_context()
		_ = context.app
		context.session_manager.is_first_run = False
		sys.argv = [sys.argv[0], str(root), str(root)]
		output = Path(os.environ.get('FIND_FILES_SMOKE_IMAGE', 'target/find-files-source.png')).resolve()
		output.parent.mkdir(parents=True, exist_ok=True)
		QTimer.singleShot(0, lambda: Thread(target=exercise, args=(context, root, output), daemon=True).start())
		if isolated:
			from fman.impl.application_context import find_plugin_dirs
			from fman.impl.plugins import SETTINGS_PLUGIN_NAME
			from unittest.mock import patch
			def focused_plugins(*args):
				return [directory for directory in find_plugin_dirs(*args) if Path(directory).name in ('Core', 'FindFiles', 'SearchFiles', SETTINGS_PLUGIN_NAME)]
			print('Isolated smoke: Core, FindFiles, SearchFiles and temporary User settings', flush=True)
			with patch('fman.impl.application_context.find_plugin_dirs', side_effect=focused_plugins):
				return context.run()
		return context.run()


if __name__ == '__main__':
	sys.exit(main())