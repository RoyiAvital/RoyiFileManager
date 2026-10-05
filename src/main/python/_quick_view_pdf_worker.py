import json
import math
import os
import stat
import struct
import sys


VERSION = 1
MAX_HEADER = 512 * 1024
MAX_PAYLOAD = 32 * 1024 * 1024
MAX_FILE = 64 * 1024 * 1024
MAX_PAGES = 2000
MAX_EDGE = 8192
MAX_PIXELS = 8000000
MAX_PAGE_POINTS = 10000000
IDENTITY = ('epoch', 'generation', 'operation', 'revision')


class PdfError(ValueError):
	pass


def valid_raster(width, height):
	return (type(width) is int and type(height) is int and
		0 < width <= MAX_EDGE and 0 < height <= MAX_EDGE and
		width * height <= MAX_PIXELS)


def valid_geometry(size):
	return (isinstance(size, (list, tuple)) and len(size) == 2 and
		all(type(value) in (int, float) and math.isfinite(value) and
			0 < value <= MAX_PAGE_POINTS for value in size))


def decode_header(data):
	try:
		header = json.loads(data)
	except (ValueError, UnicodeError, RecursionError) as error:
		raise PdfError('Invalid PDF helper header') from error
	if not isinstance(header, dict) or type(header.get('version')) is not int or header['version'] != VERSION:
		raise PdfError('Incompatible PDF helper')
	length = header.get('length')
	if type(length) is not int or not 0 <= length <= MAX_PAYLOAD:
		raise PdfError('Invalid PDF helper payload length')
	return header


def encode_frame(header, payload=b''):
	if len(payload) > MAX_PAYLOAD:
		raise PdfError('PDF page exceeds memory allowance')
	data = json.dumps(dict(header, version=VERSION, length=len(payload)),
		separators=(',', ':'), allow_nan=False).encode('utf-8')
	if not 0 < len(data) <= MAX_HEADER:
		raise PdfError('PDF helper header exceeds limit')
	return struct.pack('<I', len(data)) + data + payload


class FrameDecoder:
	def __init__(self):
		self.buffer = bytearray()
		self.header = None
		self.header_size = None

	def feed(self, data):
		if len(self.buffer) + len(data) > MAX_HEADER + MAX_PAYLOAD + 4:
			raise PdfError('PDF helper output exceeds limit')
		self.buffer.extend(data)
		frames = []
		while True:
			if self.header_size is None:
				if len(self.buffer) < 4:
					break
				self.header_size = struct.unpack_from('<I', self.buffer)[0]
				if not 0 < self.header_size <= MAX_HEADER:
					raise PdfError('Invalid PDF helper header length')
			if self.header is None:
				if len(self.buffer) < 4 + self.header_size:
					break
				self.header = decode_header(bytes(self.buffer[4:4 + self.header_size]))
			end = 4 + self.header_size + self.header['length']
			if len(self.buffer) < end:
				break
			frames.append((self.header, bytes(self.buffer[4 + self.header_size:end])))
			del self.buffer[:end]
			self.header = self.header_size = None
		return frames

	def finish(self):
		if self.buffer or self.header is not None or self.header_size is not None:
			raise PdfError('PDF helper closed an incomplete message')


def read_exact(stream, length):
	parts = bytearray()
	while len(parts) < length:
		chunk = stream.read(length - len(parts))
		if not chunk:
			raise EOFError('PDF helper input closed')
		parts.extend(chunk)
	return bytes(parts)


def read_command(stream):
	length = struct.unpack('<I', read_exact(stream, 4))[0]
	if not 0 < length <= MAX_HEADER:
		raise PdfError('Invalid PDF helper header length')
	header = decode_header(read_exact(stream, length))
	if header['length'] or header.get('type') not in ('open', 'render', 'close'):
		raise PdfError('Invalid PDF helper command')
	if any(type(header.get(key)) is not int or header[key] < 0 for key in IDENTITY):
		raise PdfError('Invalid PDF helper operation identity')
	return header


def fingerprint(info):
	return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


class Document:
	def __init__(self):
		self.pdf = None
		self.source = None
		self.sizes = ()
		self.fingerprint = ()
		self.backend = None

	def open(self, path):
		self.close()
		if not isinstance(path, str) or not os.path.isabs(path):
			raise PdfError('Invalid PDF path')
		before = os.stat(path)
		if not stat.S_ISREG(before.st_mode):
			raise PdfError('Not a regular file')
		if before.st_size > MAX_FILE:
			raise PdfError('PDF exceeds 64 MiB')
		with open(path, 'rb') as stream:
			if fingerprint(before) != fingerprint(os.fstat(stream.fileno())):
				raise PdfError('File changed while loading')
			data = bytearray()
			while len(data) <= MAX_FILE:
				chunk = stream.read(min(1024 * 1024, MAX_FILE + 1 - len(data)))
				if not chunk:
					break
				data.extend(chunk)
			if len(data) > MAX_FILE:
				raise PdfError('PDF exceeds 64 MiB')
			if fingerprint(before) != fingerprint(os.fstat(stream.fileno())):
				raise PdfError('File changed while loading')
		if fingerprint(before) != fingerprint(os.stat(path)):
			raise PdfError('File changed while loading')
		try:
			import pypdfium2
		except (ImportError, OSError) as error:
			raise PdfError('PDF renderer unavailable') from error
		self.backend = pypdfium2
		if any(flag.lower() in ('v8', 'xfa') for flag in pypdfium2.PDFIUM_INFO.flags):
			raise PdfError('Unsupported PDF renderer build')
		self.source = bytes(data)
		del data
		try:
			self.pdf = pypdfium2.PdfDocument(self.source, password='')
			count = len(self.pdf)
			if not 0 < count <= MAX_PAGES:
				raise PdfError('PDF must contain 1 to 2,000 pages')
			sizes = []
			for page_index in range(count):
				size = self.pdf.get_page_size(page_index)
				if not valid_geometry(size):
					raise PdfError('Invalid PDF page dimensions')
				sizes.append(tuple(size))
			self.sizes = tuple(sizes)
			self.fingerprint = fingerprint(before)
		except Exception:
			self.close()
			raise
		return {'sizes': self.sizes, 'fingerprint': self.fingerprint}

	def render(self, page_index, width, height):
		if self.pdf is None or type(page_index) is not int or not 0 <= page_index < len(self.sizes):
			raise PdfError('Invalid PDF page')
		if not valid_raster(width, height):
			raise PdfError('PDF raster exceeds limits')
		page_width, page_height = self.sizes[page_index]
		scale = math.nextafter(min(width / page_width, height / page_height), 0)
		page = self.pdf[page_index]
		try:
			bitmap = page.render(scale=scale, force_bitmap_format=self.backend.raw.FPDFBitmap_BGRx,
				rev_byteorder=False, draw_annots=False, fill_color=(255, 255, 255, 255))
			try:
				if (not valid_raster(bitmap.width, bitmap.height) or bitmap.width > width or
					bitmap.height > height or bitmap.stride < bitmap.width * 4 or
					bitmap.stride * bitmap.height > MAX_PAYLOAD):
					raise PdfError('Invalid PDF bitmap dimensions')
				pixels = bytearray(bitmap.buffer)
				if bitmap.stride != bitmap.width * 4:
					pixels = bytearray().join(pixels[row * bitmap.stride:row * bitmap.stride + bitmap.width * 4]
						for row in range(bitmap.height))
				pixels[3::4] = b'\xff' * (bitmap.width * bitmap.height)
				return {'page': page_index, 'width': bitmap.width, 'height': bitmap.height,
					'stride': bitmap.width * 4, 'fingerprint': self.fingerprint}, bytes(pixels)
			finally:
				bitmap.close()
		finally:
			page.close()

	def close(self):
		if self.pdf is not None:
			self.pdf.close()
		self.pdf = self.source = None
		self.sizes = self.fingerprint = ()


def binary_stream(name, identifier, mode):
	stream = getattr(sys, name)
	if stream is not None:
		return stream.buffer
	import ctypes
	import msvcrt
	from ctypes import wintypes
	get_handle = ctypes.WinDLL('kernel32', use_last_error=True).GetStdHandle
	get_handle.argtypes = (wintypes.DWORD,)
	get_handle.restype = wintypes.HANDLE
	handle = get_handle(identifier & 0xffffffff)
	if not handle or handle == ctypes.c_void_p(-1).value:
		raise OSError('PDF helper pipe unavailable')
	flags = os.O_BINARY | (os.O_RDONLY if mode == 'rb' else os.O_WRONLY)
	return os.fdopen(msvcrt.open_osfhandle(handle, flags), mode, buffering=0)


def main():
	reader = binary_stream('stdin', -10, 'rb')
	writer = binary_stream('stdout', -11, 'wb')
	document = Document()
	def send(header, payload=b''):
		writer.write(encode_frame(header, payload))
		writer.flush()
	send({'type': 'ready'})
	try:
		while True:
			command = read_command(reader)
			identity = {key: command[key] for key in IDENTITY}
			if command['type'] == 'close':
				return 0
			try:
				if command['type'] == 'open':
					result = document.open(command.get('path'))
					send(dict(identity, type='document', **result))
				else:
					result, pixels = document.render(command.get('page'), command.get('width'), command.get('height'))
					send(dict(identity, type='page', **result), pixels)
			except Exception as error:
				send(dict(identity, type='error', message=str(error)[:512] or 'Cannot preview PDF',
					page=command.get('page') if command['type'] == 'render' else None))
	except EOFError:
		return 0
	finally:
		document.close()


if __name__ == '__main__':
	sys.exit(main())