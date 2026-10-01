from fman import show_alert, OK, CANCEL
from fman.impl.html_style import highlight as b, underline as u
from fman.impl.product import APP_NAME

class UsageHelper:
	def __init__(self, is_first_run):
		self._is_first_run = is_first_run
	def on_location_bar_clicked(self, pane, outcome):
		return self._on_mouse_action(pane, outcome)
	def on_doubleclicked(self, pane, outcome):
		return self._on_mouse_action(pane, outcome)
	def on_context_menu(self, pane, via, outcome):
		return via == 'Mouse' and self._on_mouse_action(pane, outcome)
	def _on_mouse_action(self, pane, outcome):
		if not self._is_first_run:
			return False
		last, aborts = outcome
		if last == 'aborted' and aborts == 1:
			response = show_alert(
				"Hey, sorry to bother again. You just used the mouse. That "
				f"works, but {APP_NAME} is optimized for the keyboard. "
				"Would you like to see the short tutorial?",
				OK | CANCEL, OK
			)
			if response == OK:
				pane.run_command('tutorial', {'step': 1})
			return True
		if last == 'completed':
			show_alert(
				"Hey, sorry to bother one last time. You just used the mouse. "
				f"To make the most of {APP_NAME}, use the keyboard:"
				"<ul>"
					"<li>Jump to files by typing their name.</li>"
					"<li>Use %s to open them.</li>"
					"<li>Press %s to go up.</li>"
					"<li>To open a different %sath, use %s.</li>"
					"<li>For other features, press %s.</li>"
				"</ul>"
				"It's like riding a bike: With a little practice, you'll be "
				"faster than ever before!" % (
					b('Enter'), b('Backspace'), u('P'), b('Ctrl+P'),
					b('Ctrl+Shift+P')
				)

			)
			return True
		return False