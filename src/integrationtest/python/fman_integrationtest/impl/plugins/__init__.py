from os.path import exists
from fman.url import join

class StubCommandCallback:
	def before_command(self, command_name):
		pass
	def after_command(self, command_name):
		pass

class StubTheme:
	def __init__(self):
		self.loaded_css_files = []
	def load(self, css_file_path):
		if exists(css_file_path):
			self.loaded_css_files.append(css_file_path)
		else:
			raise FileNotFoundError(css_file_path)
	def unload(self, css_file_path):
		self.loaded_css_files.remove(css_file_path)

class StubFontDatabase:
	def __init__(self):
		self.loaded_fonts = []
	def load(self, font_file):
		self.loaded_fonts.append(font_file)
	def unload(self, font_file):
		self.loaded_fonts.remove(font_file)

class StubDirectoryPaneWidget:
	def __init__(self, fs):
		self._fs = fs
		self._location = ''
		self._rows = []
		self._columns = ()
	def set_location(self, url, callback=None):
		if callback is None:
			callback = lambda: None
		url = self._fs.resolve(url)
		if url != self._location:
			self._location = url
			self._columns = self._fs.get_columns(url)
			listing = self._fs.scan(url, lambda: None)
			keys = [(column.keys(listing, True), column.keys(listing, False)) for column in self._columns]
			self._rows = [
				(join(url, name), listing.is_dir[index], [
					(column.text(listing, index), ascending[index], descending[index])
					for column, (ascending, descending) in zip(self._columns, keys)
				])
				for index, name in enumerate(listing.names)
			]
		callback()
	def get_file_under_cursor(self):
		return None