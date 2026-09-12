class DisabledMetrics:
	def __init__(self):
		self.past_events = []
	def initialize(self, callback=lambda: None):
		callback()
	def get_user(self):
		return None
	def track(self, event, properties=None):
		self.past_events.append(event)
	def update_user(self, **properties):
		pass
