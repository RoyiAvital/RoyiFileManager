from core.quicksearch_matchers import contains_chars
from fman.impl.ui import Resource, UiOwner, match_positions, resource, utf16_span
from unittest import TestCase
from unittest.mock import Mock
from fman.impl.navigation import NavigationRequest, current_request


class UiStateTest(TestCase):
	def test_controller_requires_loader_owner(self):
		from fman.ui import UiController
		class Controller(UiController):
			pass
		with self.assertRaisesRegex(RuntimeError, 'active plug-in owner'):
			Controller.require_owner()
		Controller.owner = UiOwner()
		self.assertIs(Controller.owner, Controller.require_owner())
		Controller.owner.invalidate()
		with self.assertRaises(RuntimeError):
			Controller.require_owner()

	def test_casefold_offsets_refer_to_original_characters(self):
		self.assertEqual((2,), match_positions(contains_chars, 'Ma\u00dfe', 'ss'))
		self.assertEqual((0, 4), match_positions(contains_chars, 'Stra\u00dfe', 'sS'))
		self.assertIsNone(match_positions(contains_chars, 'Alpha', 'z'))

	def test_astral_highlights_use_utf16_positions(self):
		self.assertEqual((0, 2), utf16_span('\U0001f600Name', 0))
		self.assertEqual((2, 1), utf16_span('\U0001f600Name', 1))

	def test_resource_is_stable_and_snapshots_are_revisioned(self):
		self.assertIs(resource('test'), resource('test'))
		state = Resource()
		received = []
		callback = lambda revision, rows: received.append((revision, rows))
		self.assertEqual((0, ('old',)), state.subscribe(callback, lambda: ('old',)))
		with state.lock:
			notification = state.committed(('new',))
		self.assertEqual([], received)
		state.publish(notification)
		self.assertEqual([(1, ('new',))], received)
		state.unsubscribe(callback)
		with state.lock:
			notification = state.committed(())
		state.publish(notification)
		self.assertEqual(1, len(received))

	def test_owner_disposes_once_and_rejects_new_sessions(self):
		owner = UiOwner()
		disposed = []
		self.assertTrue(owner.attach(lambda: disposed.append(True)))
		owner.invalidate()
		owner.invalidate()
		self.assertEqual([True], disposed)
		self.assertFalse(owner.attach(lambda: None))

	def test_navigation_preserves_command_arguments_and_rejects_untracked(self):
		outcomes = []
		request = NavigationRequest(lambda *result: outcomes.append(result))
		pane = Mock()
		pane.run_command.side_effect = lambda *args: self.assertIs(request, current_request())
		request.dispatch(pane, 'file:///C:/Target')
		pane.run_command.assert_called_once_with('open_directory', {'url': 'file:///C:/Target'})
		self.assertEqual('failure', outcomes[0][0])
		self.assertIsNone(current_request())
		request.finish('success')
		self.assertEqual(1, len(outcomes))

	def test_canceled_navigation_never_dispatches(self):
		pane = Mock()
		request = NavigationRequest(lambda *args: None, allowed=lambda: False)
		request.dispatch(pane, 'file:///C:/Target')
		pane.run_command.assert_not_called()

	def test_navigation_keeps_command_and_location_rewrite_hooks(self):
		from fman import DirectoryPane
		from fman.impl.navigation import tracking
		registry, widget, listener = Mock(), Mock(), Mock()
		pane = DirectoryPane(None, widget, registry)
		pane._add_listener(listener)
		listener.on_command.side_effect = [('open_directory', {'url': 'zip:///C:/a.zip'}), None]
		listener.before_location_change.side_effect = [('zip:///C:/a.zip/folder', '', True), None]
		request = NavigationRequest(lambda *args: None)
		def command(name, args, target):
			self.assertIs(pane, target)
			self.assertEqual('zip:///C:/a.zip', args['url'])
			target.set_path(args['url'])
			request.started = True
		registry.execute_command.side_effect = command
		request.dispatch(pane, 'file:///C:/a.zip')
		self.assertEqual('zip:///C:/a.zip/folder', widget.set_location.call_args.args[0])
		other = DirectoryPane(None, Mock(), registry)
		with tracking(request):
			other.set_path('file:///C:/Other')
		other._widget.set_location.assert_not_called()

	def test_cancel_before_initialization_settles_and_releases_work_slot(self):
		from fman.impl.ui import submit_work
		from threading import Event
		for attempt in range(3):
			request = NavigationRequest(lambda *args: None)
			finished = Event()
			request.started = True
			self.assertTrue(submit_work(lambda: request.wait(1), lambda *args: finished.set()))
			request.cancel()
			self.assertTrue(request.settled.wait(1))
			self.assertTrue(finished.wait(1))
			self.assertFalse(request.begin_initialization())

	def test_timeout_settles_once_and_running_initializations_stay_bounded(self):
		outcomes = []
		requests = [NavigationRequest(lambda *args: outcomes.append(args)) for index in range(3)]
		try:
			self.assertTrue(requests[0].begin_initialization())
			self.assertTrue(requests[1].begin_initialization())
			requests[0].wait(0)
			requests[1].cancel()
			self.assertFalse(requests[2].begin_initialization())
			self.assertTrue(all(request.settled.is_set() for request in requests))
			requests[0].finish('success')
			self.assertEqual(3, len(outcomes))
		finally:
			for request in requests:
				request.end_initialization()