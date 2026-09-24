"""Existing scale measurements, invoked individually through run.py."""

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic, perf_counter
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch
from zipfile import ZipFile

from fman.url import as_url
from search_file_fuzzy.indexer import build_index
from search_file_fuzzy.matcher import Matcher, SearchEntry, normalize
from fman_unittest import test_pane_arch_poc as poc_tests
from fman_integrationtest import test_find_files_engine as fd_tests
from fman_integrationtest import test_qt as qt_tests
from core.tests.fs import test_zip as zip_tests
from find_files.engine import Runner
from PyQt5.QtCore import Qt


poc = poc_tests.poc
Extract = zip_tests.Extract
StubFS = zip_tests.StubFS
ZipFileSystem = zip_tests.ZipFileSystem
_run_7zip = zip_tests._run_7zip
_tree_digest = zip_tests._tree_digest
setUpModule = qt_tests.setUpModule
tearDownModule = qt_tests.tearDownModule

class SearchPerformanceTest(TestCase):
	def test_incremental_cost(self):
		from statistics import median
		from time import perf_counter
		cases = (
			('ordinary contiguous', 'report', 'report'),
			('ordinary subsequence', 'rpt', 'rpt'),
			('ordinary multi-term', 'report py', 'report py'),
			('contiguous + exclusion', 'report', 'report !missing'),
			('subsequence + exclusion', 'rpt', 'rpt !missing'),
			('subsequence + prefix', 'rpt', '^src rpt'),
		)
		for count in (1000, 10000, 50000):
			entries = [SearchEntry(str(index), 'report%05d.py' % index,
				'src/folder%03d/report%05d.py' % (index % 100, index))
				for index in range(count)]
			matcher = Matcher(entries)
			print('\nIncremental query cost: %s entries, milliseconds' % count, file=sys.stderr)
			for label, old_query, new_query in cases:
				def old():
					return matcher._fuzzy(normalize(old_query))
				def new():
					return matcher.matches(new_query)
				self.assertEqual(old(), [entry for entry, highlights in new()])
				timings = {'old': [], 'new': []}
				for repeat in range(9):
					operations = (('old', old), ('new', new))
					if repeat % 2:
						operations = operations[::-1]
					for name, operation in operations:
						started = perf_counter()
						found = operation()
						timings[name].append((perf_counter() - started) * 1000)
						self.assertLessEqual(len(found), 100)
				previous = median(timings['old'])
				current = median(timings['new'])
				delta = median([current_sample - previous_sample
					for previous_sample, current_sample in zip(timings['old'], timings['new'])])
				print('%-28s old=%7.2f new=%7.2f added=%+7.2f' %
					(label, previous, current, delta), file=sys.stderr)
			samples = {'regular': [], 'fuzzy': []}
			for repeat in range(11):
				modes = ('regular', 'fuzzy') if repeat % 2 else ('fuzzy', 'regular')
				for mode in modes:
					started = perf_counter()
					measured = Matcher(entries, mode=mode)
					elapsed = (perf_counter() - started) * 1000
					if repeat:
						samples[mode].append(elapsed)
					if mode == 'fuzzy':
						extra_bytes = sys.getsizeof(measured._literal_paths) + \
							sum(map(sys.getsizeof, measured._literal_paths))
					del measured
			delta = median([current - previous
				for previous, current in zip(samples['regular'], samples['fuzzy'])])
			print('Construction: without literal cache=%.2f with cache=%.2f added=%+.2f ms; cache=%.2f MiB' %
				(median(samples['regular']), median(samples['fuzzy']), delta, extra_bytes / 2**20),
				file=sys.stderr)

	def test_fifty_thousand_entries(self):
		from statistics import median
		from time import perf_counter
		import tracemalloc
		entries = [SearchEntry(str(index), 'report%05d.py' % index,
			'src/folder%03d/report%05d.py' % (index % 100, index))
			for index in range(50_000)]
		started = perf_counter()
		matcher = Matcher(entries)
		print('\nMatcher construction: %.1f ms' % ((perf_counter() - started) * 1000), file=sys.stderr)
		checks = [('old scoring baseline', lambda: matcher._fuzzy(normalize('report py')))]
		queries = ('report py', "'report", '^src', '.py$', '!tmp',
			"'missing", '^missing', '.missing$', '!report', '^src rpt',
			'^missing rpt', "'report rpt", 'r | p')
		checks.extend((query, lambda query=query: matcher.matches(query)) for query in queries)
		for name, operation in checks:
			operation()
			samples = []
			for repeat in range(7):
				started = perf_counter()
				found = operation()
				samples.append((perf_counter() - started) * 1000)
			self.assertLessEqual(len(found), 100)
			print('%-22s median=%7.2f ms max=%7.2f ms' %
				(name, median(samples), max(samples)), file=sys.stderr)
		tracemalloc.start()
		try:
			measured = Matcher(entries)
			current, peak = tracemalloc.get_traced_memory()
			self.assertEqual(100, len(measured('')))
			print('Matcher allocation: current=%.1f MiB peak=%.1f MiB' %
				(current / 2**20, peak / 2**20), file=sys.stderr)
		finally:
			tracemalloc.stop()


class SearchMetadataPerformanceTest(TestCase):
	def test_fifty_thousand_file_index_and_result_formatting(self):
		from collections import namedtuple
		from search_file_fuzzy import _IndexFiles, describe_metadata
		from statistics import median
		from threading import Event
		from time import perf_counter
		import tracemalloc
		with TemporaryDirectory() as root:
			for folder_number in range(100):
				folder = Path(root) / ('folder%03d' % folder_number)
				folder.mkdir()
				for file_number in range(500):
					(folder / ('report%03d.txt' % file_number)).touch()
			url = as_url(root)
			options = dict(recursive=True, max_entries=51_000, include_hidden=True)
			timings = {False: [], True: []}
			def index(enabled):
				if enabled:
					task = _IndexFiles(url, options, Event())
					task()
					return task.index
				return build_index(url, **options)
			for repeat in range(5):
				for enabled in ((False, True) if repeat % 2 == 0 else (True, False)):
					started = perf_counter()
					result = index(enabled)
					timings[enabled].append((perf_counter() - started) * 1000)
					self.assertEqual(50_000, len(result.entries))
					self.assertFalse(result.truncated)
					del result
			for enabled in (False, True):
				tracemalloc.start()
				try:
					result = index(enabled)
					current, peak = tracemalloc.get_traced_memory()
				finally:
					tracemalloc.stop()
				print('Metadata %s: 50,000 files, median %.2f ms, retained %.2f MiB, peak %.2f MiB' %
					(enabled, median(timings[enabled]), current / 2**20, peak / 2**20), file=sys.stderr)
				if enabled:
					returned = Matcher(result.entries).matches("'report")
					formats = []
					for repeat in range(21):
						started = perf_counter()
						descriptions = [describe_metadata(entry) for entry, highlights in returned]
						formats.append((perf_counter() - started) * 1000)
					self.assertEqual(100, len(descriptions))
					self.assertTrue(all(text.endswith(', 0 B') for text in descriptions))
					print('100 metadata descriptions: median %.3f ms' % median(formats), file=sys.stderr)
				del result
		previous = namedtuple('PreviousEntry', 'url name relative_path')
		overhead = sys.getsizeof(SearchEntry('', '', '')) - sys.getsizeof(previous('', '', ''))
		print('Record-slot overhead at 50,000 entries: %d bytes' % (50_000 * overhead), file=sys.stderr)


@skipUnless(sys.platform == 'win32', 'Windows memory counters')
class ImageMemoryTest(TestCase):
	def test_128mp_peak_in_fresh_process(self):
		from pathlib import Path
		from tempfile import TemporaryDirectory
		from PyQt5.QtGui import QImage, QColor
		with TemporaryDirectory() as temporary:
			path = Path(temporary) / '128mp.png'
			image = QImage(16000, 8000, QImage.Format_ARGB32)
			image.fill(QColor(30, 100, 170, 128))
			self.assertTrue(image.save(str(path), 'PNG'))
			del image
			code = '''
from fman.impl.quick_view_images import ImageLoader, ImageRequest, load_image, MAX_IMAGE_BYTES
from fman.url import as_url
from time import perf_counter
from PyQt5.QtCore import QCoreApplication, QObject, QTimer, Qt, pyqtSignal
import sys, win32api, win32process
app = QCoreApplication([])
class Delivery(QObject):
	ready = pyqtSignal()
delivery = Delivery()
loader = ImageLoader(delivery.ready.emit, lambda request, canceled: load_image(request, canceled, lambda url: url))
results = []
ticks = []
timer = QTimer()
timer.setInterval(10)
timer.timeout.connect(lambda: ticks.append(perf_counter()))
timer.start()
def receive():
	packet = loader.take_result()
	if packet is not None:
		results.append(packet[1])
		ticks.append(perf_counter())
		app.quit()
delivery.ready.connect(receive, Qt.QueuedConnection)
handle = win32api.GetCurrentProcess()
before = win32process.GetProcessMemoryInfo(handle)['WorkingSetSize']
started = perf_counter()
ticks.append(started)
loader.submit(ImageRequest(loader.invalidate(), as_url(sys.argv[1])))
QTimer.singleShot(90000, app.quit)
app.exec_()
assert results, 'Image delivery timed out'
result = results.pop()
assert result.image is not None, result.message
assert result.image.sizeInBytes() == MAX_IMAGE_BYTES
assert (result.image.width(), result.image.height()) == (16000, 8000)
assert result.image.pixelColor(15999, 7999).alpha() == 128
memory = win32process.GetProcessMemoryInfo(handle)
max_gap = max(later - earlier for earlier, later in zip(ticks, ticks[1:]))
print('128 MP: %.3f s; buffer %.2f MiB; incremental peak %.2f MiB; max Qt heartbeat gap %.1f ms' %
    (perf_counter() - started, result.image.sizeInBytes() / 1048576,
	(memory['PeakWorkingSetSize'] - before) / 1048576, max_gap * 1000), flush=True)
loader.close()
del result
print('After release: %.2f MiB above baseline' %
    ((win32process.GetProcessMemoryInfo(handle)['WorkingSetSize'] - before) / 1048576), flush=True)
assert max_gap < .1, 'Qt heartbeat gap exceeded the 100 ms target'
'''
			result = subprocess.run([sys.executable, '-c', code, str(path)], capture_output=True, text=True, timeout=120)
			self.assertEqual(0, result.returncode, result.stderr)
			print(result.stdout, end='')


class TimingTest(TestCase):
	"""Synthetic 100k-entry listing; asserts generous bounds and prints timings."""

	SIZE = 100_000

	def test_sort_and_filter_budget(self):
		names = ['%06d_%s.jpg' % (i, 'ab'[i % 2]) for i in range(self.SIZE)]
		listing = poc.Listing('x', names, [False] * self.SIZE, list(range(self.SIZE)),
			list(range(self.SIZE)), [0] * self.SIZE, [n.casefold() for n in names])
		started = perf_counter()
		order = poc.sort_order(listing, 'name')
		sort_ms = (perf_counter() - started) * 1000
		filter_ = poc.Filter(listing, order)
		started = perf_counter()
		substring = filter_.apply('9')
		substring_ms = (perf_counter() - started) * 1000
		started = perf_counter()
		fuzzy = poc.Filter(listing, order).apply('9a', 'fuzzy')
		fuzzy_ms = (perf_counter() - started) * 1000
		print('\n%d entries: natural sort %.0f ms, substring %.1f ms (%d rows), fuzzy %.1f ms (%d rows)' % (
			self.SIZE, sort_ms, substring_ms, len(substring), fuzzy_ms, len(fuzzy)))
		self.assertEqual(self.SIZE, len(order))
		self.assertLess(sort_ms, 2000)
		self.assertLess(substring_ms, 500)
		self.assertLess(fuzzy_ms, 1000)


class FindFilesPerformance(fd_tests.FindFilesEngineTest):
	def test_large_tree_exact_count_and_bounded_storage(self):
		import json
		import tracemalloc
		from fman.ui import TableRow
		from fman.impl.ui.table_data import TableSchema
		for directory in range(100):
			folder = self.root / ('folder-%03d' % directory)
			folder.mkdir()
			for index in range(2001):
				(folder / ('file-%04d.txt' % index)).touch()
		reports = []
		for pattern, expected in (('file-0000.txt', 100), ('*.txt', 200100)):
			runner = Runner(replace(self.options, pattern=pattern))
			tracemalloc.start()
			started = monotonic()
			try:
				result = runner.run()
				elapsed = monotonic() - started
				retained, peak = tracemalloc.get_traced_memory()
			finally:
				tracemalloc.stop()
			self.assertTrue(result.complete, result.reason)
			self.assertEqual(expected, result.total)
			self.assertEqual(min(expected, 10000), len(result.rows))
			self.assertEqual(expected > 10000, result.table_limited)
			self.assertIsNone(runner.child)
			self.assertLess(peak, 64 * 1024 * 1024)
			rows = tuple(TableRow(str(index), (hit.relative_path, str(hit.size), hit.modified), hit.path) for index, hit in enumerate(result.rows))
			self.assertEqual(rows, TableSchema(3, ('Path', 'Size', 'Modified')).snapshot(lambda: rows))
			reports.append({'pattern': pattern, 'matches': result.total, 'retained': len(rows),
				'seconds_with_tracemalloc': round(elapsed, 3), 'python_peak_bytes': peak,
				'python_retained_bytes': retained, 'cache': 'warm after fixture creation'})
		seen, resume, completed = Event(), Event(), Event()
		runner = Runner(self.options)
		accept = runner.collector.accept
		stopped_results = []
		def first_match(raw):
			accept(raw)
			seen.set()
			if not resume.wait(5):
				raise RuntimeError('Cancellation test timed out')
		def finished(result):
			stopped_results.append(result)
			completed.set()
		with patch.object(runner.collector, 'accept', side_effect=first_match):
			self.assertTrue(runner.start(finished))
			try:
				self.assertTrue(seen.wait(5))
				process = runner.child.process
				started = monotonic()
				runner.stop()
				resume.set()
				self.assertTrue(completed.wait(1))
				elapsed = monotonic() - started
				self.assertLess(elapsed, 1)
				self.assertIsNotNone(process.poll())
				self.assertEqual('Stopped', stopped_results[0].status)
				reports.append({'real_fd_stop_seconds': round(elapsed, 3)})
			finally:
				runner.stop()
				resume.set()
				self.assertTrue(completed.wait(5))
		print(json.dumps(reports), flush=True)


class PaneFilterPerformance(qt_tests.FilterBarIT):
	def test_full_update_performance(self):
		from fman.impl.filter_pattern import compile_filter
		from fman.listing import Listing
		from statistics import median
		from time import perf_counter
		pane = self.panes[0]
		model = self.run_in_app(pane._model.sourceModel)
		for size in (1000, 10000):
			names = ['Annual Report %05d %s.txt' % (index, 'a' * 200) for index in range(size)]
			def install():
				pane._filter_bar.close()
				model._listing = Listing.create(pane.get_location(), names)
				model.update()
			self.run_in_app(install)
			self.drain(pane)
			for query in ('rep', 'rep*txt', '?*?*?*?*?*?*?*?Z', 'a*a*a*a*a*a*a*a*Z', '*' * 100):
				matcher = compile_filter(query)
				matched = sum(matcher.matches(name) for name in names)
				times = []
				for repeat in range(3):
					self.set_query(query[:-1])
					started = perf_counter()
					self.key(Qt.Key_unknown, query[-1])
					times.append(perf_counter() - started)
					self.assertEqual(matched, self.run_in_app(pane._model.rowCount))
					self.assertEqual('Filter "%s": %d of %d items' % (query, matched, size), self.status())
				print('Filter %d rows %r: key-to-commit %.1fms' % (size, query[:20], median(times) * 1000))
				self.assertLess(max(times), 5, 'Filter did not settle within the regression ceiling')


class TablePerformance(qt_tests.TableIT):
	def test_large_snapshot_projection_timing(self):
		from time import perf_counter
		from fman.impl.ui.table import Table
		from fman.impl.ui.table_data import TableRow, TableSchema
		ready = Event()
		rows = tuple(TableRow(str(index), ('folder/file-%05d.txt' % index,
			'A long matching text snippet ' * 16)) for index in range(10000))
		def prepare():
			started = perf_counter()
			schema = TableSchema(2, ('File Path', 'Snippet'))
			widget = Table(schema, schema.snapshot(lambda: rows))
			construction = perf_counter() - started
			widget.state_changed.connect(lambda: ready.set() if widget.model.matches else None)
			started = perf_counter()
			widget.query.setText('fl9')
			return widget, construction, started
		widget, construction, started = self.run_in_app(prepare)
		try:
			self.assertTrue(ready.wait(10))
			elapsed = perf_counter() - started
			print('Table 10000 rows: snapshot/construction %.3f s; fuzzy %.3f s' % (construction, elapsed))
			self.assertGreater(self.run_in_app(widget.model.rowCount), 0)
		finally:
			self.run_in_app(widget.dispose)
			self.run_in_app(widget.deleteLater)


class ArchivePerformance(zip_tests.SevenZipExecutableTest):
	def test_copy_verification_timing(self):
		with TemporaryDirectory() as directory:
			root = Path(directory)
			archive = root / 'timing.zip'
			with ZipFile(archive, 'w') as writer:
				writer.writestr('payload.bin', b'x' * (8 * 1024 * 1024))
			started = monotonic()
			_run_7zip(['x', str(archive), '-o' + str(root / 'baseline')])
			baseline = monotonic() - started
			started = monotonic()
			Extract(StubFS(), str(archive), '', str(root / 'verified'), verify_output=True)()
			verified = monotonic() - started
			self.assertEqual(_tree_digest(root / 'baseline', lambda: None),
				_tree_digest(root / 'verified', lambda: None))
			print('8 MiB baseline extraction %.3fs; staged/verified extraction %.3fs' % (baseline, verified))
	def test_multi_item_move_verification_cost(self):
		with TemporaryDirectory() as directory:
			root = Path(directory)
			archive = root / 'timing.zip'
			output = root / 'output'
			output.mkdir()
			payload = b'x' * (3 * 1024 * 1024)
			retained = b'y' * (4 * 1024 * 1024)
			names = ['item-%02d.bin' % number for number in range(20)]
			with ZipFile(archive, 'w') as writer:
				for name in names:
					writer.writestr(name, payload)
				writer.writestr('retained.bin', retained)
			filesystem = ZipFileSystem(StubFS(), {'.zip'})
			original_open = Path.open
			read_bytes = {'archive': 0, 'output': 0}
			@contextmanager
			def counted_open(path, *args, **kwargs):
				with original_open(path, *args, **kwargs) as stream:
					def read(*read_args):
						data = stream.read(*read_args)
						kind = 'archive' if path == archive else 'output'
						read_bytes[kind] += len(data)
						return data
					proxy = Mock(wraps=stream)
					proxy.read.side_effect = read
					yield proxy
			def measured_digest(path, check):
				with patch.object(Path, 'open', counted_open):
					return _tree_digest(path, check)
			samples = []
			print('20-item Move, 64 MiB stored ZIP payload; Python hash-read bytes only')
			for name in names:
				read_bytes.update(archive=0, output=0)
				archive_size = archive.stat().st_size
				started = monotonic()
				with patch('core.fs.zip._tree_digest', side_effect=measured_digest):
					filesystem.move(as_url(archive, 'zip://') + '/' + name, as_url(output / name))
				elapsed = monotonic() - started
				self.assertEqual(2 * archive_size, read_bytes['archive'])
				self.assertEqual(2 * len(payload), read_bytes['output'])
				self.assertEqual(payload, (output / name).read_bytes())
				samples.append((elapsed, read_bytes['archive'], read_bytes['output']))
				print('%s %.3fs archive=%d output=%d' % (name, *samples[-1]))
			with ZipFile(archive) as reader:
				self.assertEqual(['retained.bin'], reader.namelist())
				self.assertEqual(retained, reader.read('retained.bin'))
			self.assertEqual(set(names), {path.name for path in output.iterdir()})
			self.assertEqual({'timing.zip', 'output'}, {path.name for path in root.iterdir()})
			print('Total %.3fs archive=%d output=%d' % (
				sum(sample[0] for sample in samples),
				sum(sample[1] for sample in samples),
				sum(sample[2] for sample in samples)
			))
