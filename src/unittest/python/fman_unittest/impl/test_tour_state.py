from concurrent.futures import ThreadPoolExecutor
from unittest import TestCase
from unittest.mock import Mock, patch

from fman import CANCEL, OK
from fman.impl.controller import Controller
from fman.impl.plugins import CommandCallback
from fman.impl.tour_state import TourState
from fman.impl.usage_helper import UsageHelper
from PyQt5.QtGui import QContextMenuEvent


class TourStateTest(TestCase):
	def test_empty_consumed_and_intervening_activity(self):
		state = TourState()
		self.assertEqual((None, 0), state.take())
		state.finished('aborted')
		self.assertEqual(('aborted', 1), state.take())
		self.assertEqual((None, 1), state.take())
		state.finished('completed')
		state.activity()
		self.assertEqual((None, 1), state.take())

	def test_abort_state_is_bounded(self):
		state = TourState()
		for _ in range(10000):
			state.finished('aborted')
		self.assertEqual(('aborted', 2), state.take())
		state.finished('completed')
		self.assertEqual(('completed', 2), state.take())
		with self.assertRaises(ValueError):
			state.finished('invalid')

	def test_concurrent_consumers_receive_outcome_once(self):
		state = TourState()
		state.finished('completed')
		with ThreadPoolExecutor(max_workers=8) as workers:
			outcomes = list(workers.map(lambda _: state.take(), range(100)))
		self.assertEqual(1, outcomes.count(('completed', 0)))
		self.assertEqual(99, outcomes.count((None, 0)))


class TourStateWiringTest(TestCase):
	def test_tutorial_folder_selection_advances_and_clears_outcome(self):
		from fman.impl.onboarding.tutorial import Tutorial
		from tempfile import TemporaryDirectory
		tour = Tutorial(False, Mock(), self.pane, Mock(), CommandCallback(self.state), self.state)
		tour._curr_step = Mock()
		tour._curr_step_index = 1
		tour._get_src_url = Mock(return_value='file://C:/start')
		tour._go_to_src_url = Mock()
		self.state.finished('completed')
		with TemporaryDirectory() as folder, \
			patch('fman.impl.onboarding.tutorial.QFileDialog.getExistingDirectory', return_value=folder), \
			patch('fman.impl.util.qt.thread.Executor.instance') as executor:
			executor.return_value.run_in_thread.side_effect = lambda thread, function, args, kwargs: function(*args, **kwargs)
			tour._pick_folder()
		self.assertEqual(2, tour._curr_step_index)
		self.assertEqual((None, 0), self.state.take())
		tour._go_to_src_url.assert_called_once_with()

	def setUp(self):
		self.state = TourState()
		self.support = Mock()
		self.pane, self.widget = Mock(), Mock()
		self.controller = Controller(self.support, Mock(), UsageHelper(True), self.state)
		self.controller.register_pane(self.widget, self.pane)

	def test_first_abort_location_prompt_consumed_on_accept_and_cancel(self):
		for answer in (OK, CANCEL):
			with self.subTest(answer=answer), patch('fman.impl.usage_helper.show_alert', return_value=answer) as alert:
				self.setUp()
				self.state.finished('aborted')
				self.controller.on_location_bar_clicked(self.widget)
				alert.assert_called_once()
				self.pane._broadcast.assert_not_called()
				if answer == OK:
					self.pane.run_command.assert_called_once_with('tutorial', {'step': 1})
				else:
					self.pane.run_command.assert_not_called()
				self.controller.on_location_bar_clicked(self.widget)
				self.pane._broadcast.assert_called_once_with('on_location_bar_clicked')
				self.assertEqual(1, alert.call_count)

	@patch('fman.impl.usage_helper.show_alert')
	def test_second_abort_and_returning_user_do_not_prompt(self, alert):
		self.state.finished('aborted')
		self.state.finished('aborted')
		self.controller.on_doubleclicked(self.widget, 'file://C:/entry')
		self.pane._broadcast.assert_called_once_with('on_doubleclicked', 'file://C:/entry')
		self.controller._usage_helper = UsageHelper(False)
		self.state.finished('completed')
		self.controller.on_location_bar_clicked(self.widget)
		alert.assert_not_called()

	@patch('fman.impl.usage_helper.show_alert')
	def test_completion_mouse_context_hint_consumed_once(self, alert):
		self.state.finished('completed')
		event = Mock()
		event.reason.return_value = QContextMenuEvent.Mouse
		self.assertEqual([], self.controller.on_context_menu(self.widget, event, 'file://C:/entry'))
		alert.assert_called_once()
		self.support.get_context_menu.assert_not_called()
		self.controller.on_context_menu(self.widget, event, 'file://C:/entry')
		self.support.get_context_menu.assert_called_once_with(self.pane, 'file://C:/entry')

	@patch('fman.impl.usage_helper.show_alert')
	def test_keyboard_and_other_context_menu_consume_without_hint(self, alert):
		for reason in (QContextMenuEvent.Keyboard, QContextMenuEvent.Other):
			self.state.finished('completed')
			event = Mock()
			event.reason.return_value = reason
			self.controller.on_context_menu(self.widget, event, None)
			self.controller.on_location_bar_clicked(self.widget)
		alert.assert_not_called()
		self.assertEqual(2, self.support.get_context_menu.call_count)

	@patch('fman.impl.usage_helper.show_alert')
	def test_command_rename_and_drop_invalidate_before_callbacks(self, alert):
		callback = CommandCallback(self.state)
		listener = Mock()
		listener.before_command.side_effect = lambda _: self.assertEqual((None, 1), self.state.take())
		callback.add_listener(listener)
		self.state.finished('aborted')
		callback.before_command('go_to')
		callback.after_command('go_to')
		listener.before_command.assert_called_once_with('go_to')
		listener.after_command.assert_called_once_with('go_to')
		for action in (self.controller.on_file_renamed, self.controller.on_files_dropped):
			self.state.finished('completed')
			self.pane._broadcast.side_effect = lambda *args: self.assertEqual((None, 1), self.state.take())
			action(self.widget, 'file://C:/entry')
			self.controller.on_location_bar_clicked(self.widget)
		alert.assert_not_called()