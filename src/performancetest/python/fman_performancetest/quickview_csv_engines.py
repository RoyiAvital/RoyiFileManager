import argparse
import csv
import ctypes
import io
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import threading
import time
import uuid


COLUMNS = ('identifier', 'name', 'category', 'code', 'note', 'path', 'sort_key', 'payload')
ROW_BYTES = 256
PAGE_ROWS = 200


def fields_for(index, padding):
    return (
        '%012d' % index, 'Item_%012d' % index, 'group%02d' % (index % 20),
        '00000123456789012345', 'caf\u00e9, "quoted"\nline two',
        'C:/data/file_%012d.csv' % index, '%012d' % (999999999999 - index),
        'x' * padding,
    )


def csv_bytes(rows):
    stream = io.StringIO(newline='')
    csv.writer(stream, lineterminator='\r\n').writerows(rows)
    return stream.getvalue().encode('utf-8')


def generate(path, size):
    header = csv_bytes([COLUMNS])
    padding = ROW_BYTES - len(csv_bytes([fields_for(0, 0)]))
    count, remainder = divmod(size - len(header), ROW_BYTES)
    if padding < 0 or count < PAGE_ROWS:
        raise ValueError('Fixture too small')
    with path.open('xb', buffering=1024 * 1024) as stream:
        stream.write(header)
        for start in range(0, count, 8192):
            end = min(start + 8192, count)
            stream.write(csv_bytes(fields_for(index, padding + (remainder if index == count - 1 else 0))
                                   for index in range(start, end)))
    if path.stat().st_size != size:
        raise AssertionError('Incorrect fixture size')
    return {'bytes': size, 'rows': count, 'padding': padding, 'extra_last': remainder}


def process_memory():
    class Counters(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong)] + [
            (name, ctypes.c_size_t) for name in (
                'PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage',
                'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage',
                'PagefileUsage', 'PeakPagefileUsage', 'PrivateUsage')]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return {'peak_working_set_mib': counters.PeakWorkingSetSize / 1024 ** 2,
            'peak_private_commit_mib': counters.PeakPagefileUsage / 1024 ** 2}


class DiskSampler:
    def __init__(self, directory):
        self.directory = directory
        self.peak = 0
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def sample(self):
        total = 0
        for directory, _, filenames in os.walk(self.directory):
            for filename in filenames:
                try:
                    total += os.stat(os.path.join(directory, filename)).st_size
                except FileNotFoundError:
                    pass
        self.peak = max(self.peak, total)
        return total

    def _run(self):
        while not self.stopped.wait(.1):
            self.sample()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stopped.set()
        self.thread.join()
        self.sample()


def check_page(rows, indices, metadata):
    expected = [fields_for(index, metadata['padding'] +
                           (metadata['extra_last'] if index == metadata['rows'] - 1 else 0))
                for index in indices]
    if rows != expected:
        raise AssertionError('Incorrect page values, quoting, encoding or ordering')


def run_worker(engine, source, directory, metadata, duckdb_memory):
    started = time.perf_counter()
    database = directory / 'spool.db'
    if engine == 'sqlite':
        import sqlite3
        connection = sqlite3.connect(database)
        connection.execute('PRAGMA cache_size=-16384')
        connection.execute('PRAGMA mmap_size=0')
        connection.execute('PRAGMA temp_store=FILE')
        connection.execute('PRAGMA journal_mode=DELETE')
        connection.execute('PRAGMA synchronous=NORMAL')
        connection.execute("PRAGMA temp_store_directory='%s'" % str(directory).replace("'", "''"))
        connection.execute('CREATE TABLE rows (source_record INTEGER PRIMARY KEY, ' +
                           ', '.join(name + ' TEXT NOT NULL' for name in COLUMNS) + ')')
        version = sqlite3.sqlite_version
    else:
        import duckdb
        connection = duckdb.connect(str(database))
        connection.execute("SET memory_limit='%dMiB'" % duckdb_memory)
        connection.execute('SET threads=1')
        connection.execute('SET preserve_insertion_order=false')
        connection.execute("SET temp_directory='%s'" % str(directory / 'spill').replace("'", "''"))
        connection.execute("SET max_temp_directory_size='8GiB'")
        version = duckdb.__version__
    initialized = time.perf_counter()
    with DiskSampler(directory) as disk:
        if engine == 'sqlite':
            stream = source.open('r', encoding='utf-8', newline='')
            reader = csv.reader(stream, strict=True)
            if tuple(next(reader)) != COLUMNS:
                raise AssertionError('Unexpected schema')
            first = [tuple(next(reader)) for _ in range(PAGE_ROWS)]
        else:
            schema = '{' + ', '.join("'%s': 'VARCHAR'" % name for name in COLUMNS) + '}'
            scan = ('read_csv(?, auto_detect=false, header=true, delim=\',\', quote=\'"\', '
                    'escape=\'"\', columns=' + schema + ', strict_mode=true, ignore_errors=false, '
                    'parallel=false, force_not_null=[' + ', '.join("'%s'" % name for name in COLUMNS) + '])')
            first = connection.execute('SELECT * FROM ' + scan + ' LIMIT 200', [str(source)]).fetchall()
        first_ready = time.perf_counter()
        check_page(first, range(PAGE_ROWS), metadata)
        import_start = time.perf_counter()
        if engine == 'sqlite':
            insert = 'INSERT INTO rows VALUES (' + ','.join('?' for _ in range(len(COLUMNS) + 1)) + ')'
            batch = [(index + 1,) + row for index, row in enumerate(first)]
            record = PAGE_ROWS
            for row in reader:
                if len(row) != len(COLUMNS):
                    raise AssertionError('Ragged fixture')
                record += 1
                batch.append((record,) + tuple(row))
                if len(batch) == 8192:
                    connection.executemany(insert, batch)
                    connection.commit()
                    batch.clear()
            connection.executemany(insert, batch)
            connection.commit()
            stream.close()
        else:
            connection.execute('CREATE TABLE rows AS SELECT ordinality AS source_record, ' +
                               ', '.join(COLUMNS) + ' FROM ' + scan + ' WITH ORDINALITY', [str(source)])
            connection.execute('CHECKPOINT')
        imported = time.perf_counter()
        import_disk = disk.sample()
        row_count, identifier_sum, bad_ordinals = connection.execute(
            'SELECT count(*), sum(CAST(identifier AS BIGINT)), '
            'sum(CASE WHEN CAST(identifier AS BIGINT) + 1 != source_record THEN 1 ELSE 0 END) FROM rows').fetchone()
        if row_count != metadata['rows'] or identifier_sum != row_count * (row_count - 1) // 2 or bad_ordinals:
            raise AssertionError('Incomplete or corrupted import')
        names = ', '.join('rows.' + name for name in COLUMNS)
        filter_start = time.perf_counter()
        connection.execute('CREATE TABLE filtered_result AS SELECT '
                           'row_number() OVER (ORDER BY source_record) - 1 AS position, source_record '
                           "FROM rows WHERE instr(category, 'group07') > 0")
        connection.commit()
        filtered = time.perf_counter()
        expected_matches = (row_count - 1 - 7) // 20 + 1
        matches = connection.execute('SELECT count(*) FROM filtered_result').fetchone()[0]
        if matches != expected_matches:
            raise AssertionError('Incomplete filter')
        page = connection.execute('SELECT ' + names + ' FROM filtered_result JOIN rows '
                                  'USING(source_record) ORDER BY position LIMIT 200').fetchall()
        check_page(page, range(7, min(row_count, 7 + 20 * PAGE_ROWS), 20), metadata)
        disk.sample()
        connection.execute('DROP TABLE filtered_result')
        connection.commit()
        sort_start = time.perf_counter()
        connection.execute('CREATE TABLE sorted_result AS SELECT '
                           'row_number() OVER (ORDER BY sort_key, source_record) - 1 AS position, '
                           'source_record FROM rows')
        connection.commit()
        sorted_at = time.perf_counter()
        page = connection.execute('SELECT ' + names + ' FROM sorted_result JOIN rows '
                                  'USING(source_record) ORDER BY position LIMIT 200').fetchall()
        check_page(page, range(row_count - 1, row_count - 1 - PAGE_ROWS, -1), metadata)
        if connection.execute('SELECT count(*) FROM sorted_result').fetchone()[0] != row_count:
            raise AssertionError('Incomplete full sort')
        disk.sample()
        memory = process_memory()
        connection.close()
    return dict(engine=engine, version=version, bytes=metadata['bytes'], rows=row_count,
                engine_init_s=initialized - started, first_200_s=first_ready - started,
                import_s=imported - import_start, full_ready_s=imported - started,
                filter_s=filtered - filter_start, full_sort_s=sorted_at - sort_start,
                imported_disk_mib=import_disk / 1024 ** 2, sampled_peak_disk_mib=disk.peak / 1024 ** 2,
                verified=True, **memory)


def run_latency_worker(source, metadata, duckdb_memory):
    started = time.perf_counter()
    import duckdb
    imported = time.perf_counter()
    connection = duckdb.connect()
    connection.execute('SET threads=1')
    connection.execute("SET memory_limit='%dMiB'" % duckdb_memory)
    connected = time.perf_counter()
    schema = '{' + ', '.join("'%s': 'VARCHAR'" % name for name in COLUMNS) + '}'
    options = ('auto_detect=false, header=true, delim=\',\', quote=\'"\', escape=\'"\', '
               'columns=' + schema + ', strict_mode=true, ignore_errors=false, parallel=false')
    query = 'SELECT * FROM read_csv(?, ' + options + ') LIMIT 200'
    first = connection.execute(query, [str(source)]).fetchall()
    first_ready = time.perf_counter()
    check_page(first, range(PAGE_ROWS), metadata)
    warm = []
    small_buffer = []
    reduced_query = ('SELECT * FROM read_csv(?, ' + options +
                     ', buffer_size=4194304, max_line_size=1048576) LIMIT 200')
    for _ in range(10):
        before = time.perf_counter()
        page = connection.execute(query, [str(source)]).fetchall()
        warm.append((time.perf_counter() - before) * 1000)
        check_page(page, range(PAGE_ROWS), metadata)
        before = time.perf_counter()
        page = connection.execute(reduced_query, [str(source)]).fetchall()
        small_buffer.append((time.perf_counter() - before) * 1000)
        check_page(page, range(PAGE_ROWS), metadata)
    connection.close()
    from fman.impl.quick_view_images import ImageRequest
    from fman.impl.quick_view_text import load_text, READ_LIMIT
    url = 'file://' + source.resolve().as_posix()
    request = ImageRequest(1, url)
    text_times = []
    for _ in range(3):
        before = time.perf_counter()
        text_result = load_text(request, lambda: False, resolve=lambda value: value)
        text_times.append((time.perf_counter() - before) * 1000)
        if text_result.kind != 'text' or text_result.content.byte_count != min(metadata['bytes'], READ_LIMIT):
            raise AssertionError('Unexpected actual Text View loader result')
        if text_result.content.truncated != (metadata['bytes'] > READ_LIMIT):
            raise AssertionError('Unexpected text truncation state')
    return dict(engine='duckdb', bytes=metadata['bytes'], rows=metadata['rows'], verified=True,
                module_import_ms=(imported - started) * 1000,
                connection_ms=(connected - imported) * 1000,
                first_query_ms=(first_ready - connected) * 1000,
                first_total_ms=(first_ready - started) * 1000,
                warm_median_ms=statistics.median(warm), warm_max_ms=max(warm),
                reduced_buffer_median_ms=statistics.median(small_buffer),
                reduced_buffer_max_ms=max(small_buffer), text_loader_median_ms=statistics.median(text_times),
                text_bytes=text_result.content.byte_count, text_truncated=text_result.content.truncated,
                warm_samples_ms=warm, reduced_buffer_samples_ms=small_buffer,
                text_samples_ms=text_times)


def run_parent(args):
    root = Path(args.results).resolve()
    root.mkdir(parents=True, exist_ok=True)
    run = root / (time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
    run.mkdir()
    scratch = run / 'scratch'
    scratch.mkdir()
    record = {'protocol': 'quickview-csv-engines-v3', 'python': sys.version,
              'os': platform.platform(), 'logical_cpus': os.cpu_count(), 'records': [],
              'failures': [],
              'settings': {'row_bytes': ROW_BYTES, 'columns': COLUMNS, 'repeats': args.repeat,
                           'mode': 'latency' if args.latency else 'full_pipeline',
                           'duckdb_threads': 1, 'duckdb_memory_limit_mib': args.duckdb_memory,
                           'duckdb_source_order': 'WITH ORDINALITY; preserve_insertion_order=false',
                           'sqlite_cache_mib': 16, 'cache': 'uncontrolled OS cache; not cold-cache',
                           'size_unit': 'decimal MB', 'qt_included': False,
                           'sort': 'complete disk materialization; normalized ASCII key',
                           'filter': 'complete disk materialization; case-sensitive ASCII Contains'}}
    output = run / 'results.json'
    try:
        for size_mb in args.sizes:
            size = int(size_mb * 1000000)
            if shutil.disk_usage(run).free < size * 5 + 1024 ** 3:
                raise RuntimeError('Insufficient scratch disk headroom')
            source = scratch / ('fixture-%sMB.csv' % size_mb)
            metadata = generate(source, size)
            print('Fixture:', size_mb, 'MB;', metadata['rows'], 'records', flush=True)
            for repetition in range(args.repeat):
                engines = args.engines if repetition % 2 == 0 else tuple(reversed(args.engines))
                for engine in engines:
                    directory = scratch / ('%s-%d' % (engine, repetition))
                    directory.mkdir()
                    env = dict(os.environ, TEMP=str(directory), TMP=str(directory), PYTHONHASHSEED='0')
                    if args.latency:
                        sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
                        import build
                        env.update(build._environment())
                    child = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--worker', engine,
                                            '--source', str(source), '--scratch', str(directory),
                                            '--metadata', json.dumps(metadata),
                                            '--duckdb-memory', str(args.duckdb_memory)] +
                                           (['--latency'] if args.latency else []), env=env,
                                           capture_output=True, text=True, timeout=900)
                    if child.returncode:
                        failure = dict(engine=engine, size_mb=size_mb, repetition=repetition + 1,
                                       stdout=child.stdout, stderr=child.stderr, exit_code=child.returncode)
                        record['failures'].append(failure)
                        if args.continue_on_error:
                            print('FAILED', engine, size_mb, child.stderr, flush=True)
                            shutil.rmtree(directory)
                            continue
                        raise RuntimeError('%s failed:\n%s\n%s' % (engine, child.stdout, child.stderr))
                    result = json.loads(child.stdout)
                    result.update(repetition=repetition + 1, size_mb=size_mb)
                    record['records'].append(result)
                    with output.open('w', encoding='utf-8') as stream:
                        json.dump(record, stream, indent=2)
                    print(json.dumps(result), flush=True)
                    shutil.rmtree(directory)
            source.unlink()
        record['status'] = 'completed_with_failures' if record['failures'] else 'passed'
    except BaseException as error:
        record.update(status='failed', error=repr(error))
        raise
    finally:
        with output.open('w', encoding='utf-8') as stream:
            json.dump(record, stream, indent=2)
        shutil.rmtree(scratch, ignore_errors=True)
        print('Results:', output, flush=True)
    for size_mb in args.sizes:
        for engine in args.engines:
            results = [item for item in record['records'] if item['size_mb'] == size_mb and item['engine'] == engine]
            if not results:
                continue
            keys = ('module_import_ms', 'connection_ms', 'first_query_ms', 'first_total_ms',
                    'warm_median_ms', 'reduced_buffer_median_ms', 'text_loader_median_ms') if args.latency else (
                        'first_200_s', 'full_ready_s', 'filter_s', 'full_sort_s',
                        'peak_working_set_mib', 'sampled_peak_disk_mib')
            summary = {key: round(statistics.median(item[key] for item in results), 4) for key in keys}
            print('MEDIAN', size_mb, engine, json.dumps(summary), flush=True)


def main():
    parser = argparse.ArgumentParser(description='Isolated CSV/SQLite versus DuckDB feasibility benchmark')
    parser.add_argument('--sizes', type=float, nargs='+', default=[100, 500, 2000])
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--engines', choices=['sqlite', 'duckdb'], nargs='+', default=['sqlite', 'duckdb'])
    parser.add_argument('--duckdb-memory', type=int, default=128)
    parser.add_argument('--continue-on-error', action='store_true')
    parser.add_argument('--latency', action='store_true')
    parser.add_argument('--results', default='UserSettings/Performance/QuickView005/Engines')
    parser.add_argument('--worker', choices=['sqlite', 'duckdb'])
    parser.add_argument('--source')
    parser.add_argument('--scratch')
    parser.add_argument('--metadata')
    args = parser.parse_args()
    if args.worker:
        if args.latency:
            result = run_latency_worker(Path(args.source), json.loads(args.metadata), args.duckdb_memory)
        else:
            result = run_worker(args.worker, Path(args.source), Path(args.scratch),
                        json.loads(args.metadata), args.duckdb_memory)
        print(json.dumps(result), flush=True)
    else:
        run_parent(args)


if __name__ == '__main__':
    main()