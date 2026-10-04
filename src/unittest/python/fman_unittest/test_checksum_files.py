import base64
import json
import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from checksum_files import engine


REFERENCES = Path(__file__).resolve().parents[2] / 'resources' / 'ChecksumFiles' / 'v2' / 'references.json'


class ChecksumFormatTest(TestCase):
    def test_all_reference_records_parse_and_format(self):
        fixture = json.loads(REFERENCES.read_text(encoding='utf-8'))
        for manifest in fixture['manifests']:
            algorithm = engine.algorithm_for_path(manifest['filename'])
            content = base64.b64decode(manifest['content_base64']).decode('utf-8-sig')
            count = 0
            for line in content.splitlines(keepends=True):
                record = engine.parse_record(line, algorithm)
                if record is not None:
                    with self.subTest(algorithm=algorithm.identifier, path=record.path):
                        self.assertEqual(line, engine.format_record(record.path, record.digest, algorithm, engine.Settings()))
                    count += 1
            self.assertEqual(83, count)

    def test_registry_and_strict_settings(self):
        self.assertEqual(12, len(engine.ALGORITHMS))
        self.assertEqual('sha256', engine.Settings.from_mapping({}).default_algorithm)
        self.assertEqual('utf-8-sig', engine.Settings().encoding)
        self.assertEqual('utf-8', engine.Settings(unix_format=True).encoding)
        for values in ([], {'default_algorithm': 'unknown'}, {'chunk_size_mib': True},
                       {'blake3_threads': 17}, {'filename_encoding': 'latin-1'}, {'unix_format': 1}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                engine.Settings.from_mapping(values)

    def test_aliases_and_digest_lengths(self):
        for extension, identifier in (('.SHA', 'sha1'), ('.sha1', 'sha1'), ('.bk3', 'blake3'),
                                      ('.sha3', 'sha3_256'), ('.sha3-512', 'sha3_512')):
            self.assertEqual(identifier, engine.algorithm_for_path('file' + extension).identifier)
        with self.assertRaises(ValueError):
            engine.parse_record('0' * 128 + ' *name', engine.algorithm_for_path('file.sha3'))

    def test_unsafe_paths_are_rejected(self):
        for path in ('../escape', '/root', 'C:relative', 'C:\\absolute', '\\\\host\\share',
                     '\\\\?\\C:\\device', 'file:stream', 'folder//file', 'CON.txt', 'NUL',
                     'trailing.', 'trailing ', 'bad\x00.txt', 'bad\ud800.txt'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                engine.relative_path(path)
        self.assertEqual(' leading/name', engine.relative_path('.\\ leading\\name'))
        self.assertEqual(';semicolon.txt', engine.parse_record(';semicolon.txt 00000000', engine.BY_ID['crc32']).path)
        self.assertIsNone(engine.parse_record('; comment', engine.BY_ID['crc32']))

    def test_unix_output_is_relative_and_binary(self):
        output = engine.format_record('folder\\file', 'a' * 64, engine.BY_ID['sha256'], engine.Settings(unix_format=True))
        self.assertEqual('a' * 64 + ' *folder/file\n', output)

    def test_device_aliases_are_rejected_in_every_component(self):
        for name in ('NUL .txt', 'CON .txt', 'COM1 .log', 'AUX .sha256', 'LPT\u00b9 .txt'):
            for path in (name, 'folder/' + name, name + '/file'):
                with self.subTest(path=path):
                    with self.assertRaises(ValueError):
                        engine.parse_record('a' * 64 + ' *' + path, engine.BY_ID['sha256'])
                    with self.assertRaises(ValueError):
                        engine.format_record(path, 'a' * 64, engine.BY_ID['sha256'], engine.Settings())


class ChecksumEngineTest(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.settings = engine.Settings()
        self.algorithm = engine.BY_ID['sha256']
        (self.root / 'first').write_bytes(b'abc')
        (self.root / 'folder').mkdir()
        (self.root / 'folder' / 'second').write_bytes(b'def')
        self.destination = self.root / 'checks.sha256'

    def test_selected_folder_recurses_without_siblings(self):
        result = engine.generate(str(self.root), (str(self.root / 'folder'),), str(self.destination), self.algorithm, self.settings)
        self.assertEqual(1, result.files)
        self.assertTrue(self.destination.read_bytes().startswith(b'\xef\xbb\xbf'))
        self.assertIn(' *folder\\second\r\n', self.destination.read_bytes().decode('utf-8-sig'))
        report = engine.verify(str(self.destination), self.settings)
        self.assertEqual((True, 1, 1), (report.complete, report.total, report.matched))

    def test_whole_folder_deduplicates_roots_and_excludes_destination(self):
        self.destination.write_bytes(b'old')
        identity = engine._identity(self.destination.stat())
        result = engine.generate(str(self.root), (str(self.root), str(self.root / 'folder')), str(self.destination), self.algorithm, self.settings, expected_destination=identity)
        self.assertEqual(2, result.files)
        self.assertEqual(2, engine.verify(str(self.destination), self.settings).matched)

    def test_failure_and_cancellation_preserve_existing_manifest(self):
        self.destination.write_bytes(b'old')
        identity = engine._identity(self.destination.stat())
        for error in (OSError('read failed'), engine.Canceled()):
            with self.subTest(error=error), patch.object(engine, 'hash_file', side_effect=error):
                with self.assertRaises(type(error)):
                    engine.generate(str(self.root), (), str(self.destination), self.algorithm, self.settings, expected_destination=identity)
            self.assertEqual(b'old', self.destination.read_bytes())
            self.assertEqual([], list(self.root.glob('.checksum-*.tmp')))

    def test_destination_race_preserves_replacement(self):
        def modify(amount):
            self.destination.write_bytes(b'another writer')
        with self.assertRaises(engine.ChangedFile):
            engine.generate(str(self.root), (str(self.root / 'first'),), str(self.destination), self.algorithm, self.settings, progress=modify)
        self.assertEqual(b'another writer', self.destination.read_bytes())

    def test_missing_mismatch_invalid_and_duplicates(self):
        digest = hashlib.sha256(b'abc').hexdigest()
        self.destination.write_text(digest + ' *first\n' + digest + ' *./first\n' + '0' * 64 + ' *folder/second\n' + digest + ' *missing\n' + digest + ' *../escape\n', encoding='utf-8')
        report = engine.verify(str(self.destination), self.settings)
        self.assertTrue(report.complete)
        self.assertEqual(['Matched', 'Duplicate', 'Mismatch', 'Missing', 'Invalid record'], [row.status for row in report.all_rows])
        self.assertEqual(4, len(report.problems))

    def test_changed_file_is_detected(self):
        def change(amount):
            (self.root / 'first').write_bytes(b'changed')
        with self.assertRaises(engine.ChangedFile):
            engine.hash_file(str(self.root / 'first'), self.algorithm, self.settings, progress=change)

    def test_reserved_manifest_entries_are_not_hashed_or_navigable(self):
        names = ('NUL .txt', 'CON .txt', 'COM1 .log', 'AUX .sha256')
        self.destination.write_text(''.join('a' * 64 + ' *' + name + '\n' for name in names), encoding='utf-8')
        with patch.object(engine, 'hash_file') as hash_file:
            results = engine.verify(str(self.destination), self.settings)
        hash_file.assert_not_called()
        self.assertEqual(len(names), results.total)
        self.assertEqual(['Invalid record'] * len(names), [row.status for row in results.all_rows])
        self.assertTrue(all(row.target is None for row in results.all_rows))

    def test_reserved_output_names_are_rejected_before_io(self):
        for name in ('NUL .txt', 'CON .txt', 'COM1 .log', 'AUX .sha256'):
            with self.subTest(name=name), patch.object(engine.tempfile, 'mkstemp') as staging, patch.object(engine, 'hash_file') as hashing:
                with self.assertRaises(ValueError):
                    engine.generate(str(self.root), (), str(self.root / name), self.algorithm, self.settings)
                staging.assert_not_called()
                hashing.assert_not_called()

    def test_verification_checks_shared_directories_once(self):
        calls = []
        for depth in (0, 10):
            directory = self.root.joinpath(*['nested'] * depth)
            directory.mkdir(parents=True, exist_ok=True)
            records = []
            for index in range(10):
                path = directory / ('file-' + str(index))
                path.write_bytes(b'abc')
                records.append(hashlib.sha256(b'abc').hexdigest() + ' *' + str(path.relative_to(self.root)) + '\n')
            self.destination.write_text(''.join(records), encoding='utf-8')
            with patch.object(engine.os, 'lstat', wraps=engine.os.lstat) as inspect, patch.object(engine.os, 'fstat', wraps=engine.os.fstat) as inspect_handle:
                report = engine.verify(str(self.destination), self.settings)
            self.assertEqual(10, report.matched, report.summary)
            self.assertEqual(22, inspect_handle.call_count)
            calls.append(inspect.call_count)
        self.assertEqual([33, 43], calls)

    def test_directory_check_cache_is_bounded_and_rejects_outside_paths(self):
        import stat
        checked = set()
        with patch.object(engine, '_inspect', return_value=Mock(st_mode=stat.S_IFDIR)) as inspect:
            for index in range(300):
                engine._check_chain(str(self.root), str(self.root / str(index)), checked)
            self.assertEqual(256, len(checked))
            inspect.reset_mock()
            with self.assertRaises(ValueError):
                engine._check_chain(str(self.root), str(self.root.parent / 'outside'), checked)
            inspect.assert_not_called()

    def test_empty_oversized_and_duplicate_budget(self):
        self.destination.write_bytes(b'')
        self.assertNotIn('All matched', engine.verify(str(self.destination), self.settings).summary)
        self.destination.write_bytes(b'x' * (engine.MAX_RECORD_BYTES + 1) + b'\n' + b'0' * 64 + b' *first\n')
        report = engine.verify(str(self.destination), self.settings)
        self.assertEqual(2, report.total)
        self.assertEqual('Invalid record', report.problems[0].status)
        report = engine.verify(str(self.destination), self.settings, duplicate_limit=1)
        self.assertFalse(report.complete)
        self.assertIn('bookkeeping', report.reason)

    def test_bounded_results_continue_counting_and_escape_controls(self):
        results = engine.Results(row_limit=2)
        for index in range(10):
            results.add(engine.ResultRow(index, 'bad\x00\ud800', 'Mismatch'))
        results.complete = True
        results.freeze()
        self.assertEqual(10, results.total)
        self.assertEqual(2, len(results.problems))
        self.assertIsNone(results.all_rows)
        self.assertIn('8 problem rows omitted', results.summary)
        self.assertNotIn('\x00', results.problems[0].cells[0])
        results.problems[0].cells[0].encode('utf-8')

    def test_unavailable_all_view_does_not_claim_problem_truncation(self):
        results = engine.Results(row_limit=1)
        results.add(engine.ResultRow(1, 'first', 'Matched'))
        results.add(engine.ResultRow(2, 'second', 'Matched'))
        results.complete = True
        self.assertIn('All matched', results.summary)
        self.assertIn('Showing problems only', results.summary)
        self.assertNotIn('truncated', results.summary)
        results.add(engine.ResultRow(3, 'third', 'Missing'))
        self.assertNotIn('truncated', results.summary)
        self.assertEqual(1, len(results.problems))
        results.add(engine.ResultRow(4, 'fourth', 'Mismatch'))
        self.assertIn('1 problem rows omitted', results.summary)

    def test_row_accounting_escapes_once_and_stops_when_not_retaining(self):
        row = engine.ResultRow(1, 'bad\x00\ud800', 'Mismatch', details='details\x00', target='C:\\checks\\file')
        expected_size, expected_payload = row.display_bytes, row.payload_bytes
        results = engine.Results(row_limit=1)
        with patch.object(engine, 'display_text', wraps=engine.display_text) as display:
            results.add(row)
        self.assertEqual(5, display.call_count)
        self.assertEqual((expected_size, expected_payload), (results._problem_bytes, results._problem_payload))
        with patch.object(engine, 'display_text', side_effect=AssertionError('Discarded row was formatted')):
            results.add(engine.ResultRow(2, 'second', 'Mismatch'))
            results.add(engine.ResultRow(3, 'third', 'Matched'))
            results.add(engine.ResultRow(4, 'fourth', 'Missing'))
        self.assertEqual((4, 1, 1), (results.total, results.matched, len(results.problems)))
        self.assertIsNone(results.all_rows)

    def test_root_collapse_preserves_explicit_order_and_case(self):
        first = str(self.root / 'first')
        folder = str(self.root / 'folder')
        second = str(self.root / 'folder' / 'second')
        self.assertEqual((first, folder), engine._roots(str(self.root), (first, second, folder, first)))
        self.assertEqual((str(self.root),), engine._roots(str(self.root), (first, str(self.root))))
        self.assertEqual((first, str(self.root / 'FIRST')), engine._roots(str(self.root), (first, str(self.root / 'FIRST'))))
        with self.assertRaises(ValueError):
            engine._roots(str(self.root), (str(self.root.parent / (self.root.name + '-outside')),))

    def test_known_unsupported_manifest_reports_incomplete(self):
        path = self.root / 'checks.xxh3'
        path.write_bytes(b'unknown')
        self.assertIn(str(path), engine.discover(str(self.root)))
        report = engine.verify(str(path), self.settings)
        self.assertFalse(report.complete)
        self.assertIn('Unsupported', report.reason)

    def test_display_limits_keep_problem_prefix(self):
        results = engine.Results(byte_limit=20)
        results.add(engine.ResultRow(1, 'very long name' * 10, 'Mismatch'))
        results.add(engine.ResultRow(2, '', 'Missing'))
        self.assertEqual([], results.problems)
        self.assertIsNone(results.all_rows)

    def test_hard_link_name_is_not_excluded(self):
        self.destination.write_bytes(b'old')
        os.link(self.destination, self.root / 'alias')
        result = engine.generate(str(self.root), (), str(self.destination), self.algorithm, self.settings, expected_destination=engine._identity(self.destination.stat()))
        self.assertEqual(3, result.files)
        self.assertIn(' *alias\r\n', self.destination.read_bytes().decode('utf-8-sig'))

    def test_existing_destination_case_alias_is_excluded(self):
        self.destination.write_bytes(b'old')
        destination = str(self.destination.with_name('CHECKS.sha256'))
        result = engine.generate(str(self.root), (), destination, self.algorithm, self.settings, expected_destination=engine._identity(self.destination.stat()))
        self.assertEqual(2, result.files)
        report = engine.verify(destination, self.settings)
        self.assertEqual((2, 0), (report.matched, len(report.problems)))

    def test_cancel_retains_completed_rows(self):
        digest = hashlib.sha256(b'abc').hexdigest()
        self.destination.write_text((digest + ' *first\n') * 2, encoding='utf-8')
        results = engine.Results()
        def check():
            if results.total:
                raise engine.Canceled()
        report = engine.verify(str(self.destination), self.settings, check, results=results)
        self.assertFalse(report.complete)
        self.assertEqual(1, report.matched)
        self.assertEqual('Canceled.', report.reason)

    def test_all_algorithms_stream_raw_bytes(self):
        import blake3
        for algorithm in engine.ALGORITHMS:
            with self.subTest(algorithm=algorithm.identifier), patch.object(engine, '_native_blake3', return_value=blake3.blake3):
                digest, size = engine.hash_file(str(self.root / 'first'), algorithm, self.settings)
                self.assertEqual(3, size)
                expected = '352441c2' if algorithm.identifier == 'crc32' else blake3.blake3(b'abc').hexdigest() if algorithm.identifier == 'blake3' else hashlib.new(algorithm.identifier, b'abc', usedforsecurity=False).hexdigest()
                self.assertEqual(expected, digest)

    def test_missing_private_backend_never_uses_global_installation(self):
        import sys
        with patch.object(sys, 'frozen', True, create=True), patch.dict(sys.modules, {engine.__package__ + '._vendor.blake3': None}):
            with self.assertRaisesRegex(ValueError, 'BLAKE3 dependency'):
                engine.hash_file(str(self.root / 'first'), engine.BY_ID['blake3'], self.settings)

    def test_source_run_uses_installed_native_backend(self):
        digest, size = engine.hash_file(str(self.root / 'first'), engine.BY_ID['blake3'], self.settings)
        self.assertEqual('6437b3ac38465133ffb63b75273a8db548c558465d79db03fd359c6cd5bd9d85', digest)
        self.assertEqual(3, size)

    def test_precanceled_operations_do_not_touch_filesystem(self):
        def canceled():
            raise engine.Canceled()
        with patch.object(engine, '_check_chain', side_effect=AssertionError('Canceled operation performed I/O')):
            with self.assertRaises(engine.Canceled):
                engine.generate(str(self.root), (), str(self.destination), self.algorithm, self.settings, check=canceled)
            with self.assertRaises(engine.Canceled):
                engine.discover(str(self.root), check=canceled)
            report = engine.verify(str(self.destination), self.settings, check=canceled)
        self.assertEqual('Canceled.', report.reason)
        self.assertFalse(report.complete)

    def test_blake3_reuses_serial_and_parallel_state_without_leaks(self):
        import blake3
        state = engine.HashState(self.settings)
        backend = engine.BY_ID['blake3']
        for content in (b'abc', b'', b'x' * (16 * 1024 * 1024 + 1), b'abc', b'', b'y' * (16 * 1024 * 1024 + 1)):
            (self.root / 'first').write_bytes(content)
            with patch.object(engine, '_native_blake3', return_value=blake3.blake3):
                digest, size = engine.hash_file(str(self.root / 'first'), backend, self.settings, state=state)
            self.assertEqual(blake3.blake3(content).hexdigest(), digest)
            self.assertEqual(len(content), size)
        self.assertLessEqual(len(state.blake3), 2)
        self.assertEqual(4 * 1024 * 1024, len(state.buffer))

    def test_progress_updates_are_rate_limited(self):
        callback = Mock()
        progress = engine.Progress(callback)
        with patch.object(engine.time, 'monotonic', side_effect=[1, 1.01, 1.09, 1.11]):
            for amount in (1, 2, 3, 4):
                progress(amount)
        self.assertEqual([((1,), {}), ((10,), {})], callback.call_args_list)

    def test_production_verifier_reads_all_tc_digests(self):
        import blake3
        from src.misc.generate_checksum_fixtures import generate
        fixture = json.loads(REFERENCES.read_text(encoding='utf-8'))
        corpus = self.root / 'corpus'
        generate(corpus)
        with patch.object(engine, '_native_blake3', return_value=blake3.blake3):
            for manifest in fixture['manifests']:
                path = corpus / manifest['filename']
                path.write_bytes(base64.b64decode(manifest['content_base64']))
                with self.subTest(manifest=manifest['filename']):
                    report = engine.verify(str(path), self.settings)
                    self.assertTrue(report.complete, report.reason)
                    self.assertEqual(83, report.matched, report.problems)
                    self.assertEqual((), report.problems)

    def test_reparse_records_do_not_read_or_navigate_target(self):
        self.destination.write_text('0' * 64 + ' *first\n', encoding='utf-8')
        original = engine._inspect
        def inspect(path):
            if path == str(self.root / 'first'):
                raise engine.LinkedPath('test reparse point')
            return original(path)
        with patch.object(engine, '_inspect', side_effect=inspect), patch.object(engine, 'hash_file') as hashing:
            report = engine.verify(str(self.destination), self.settings)
        hashing.assert_not_called()
        self.assertEqual('Skipped: link', report.problems[0].status)
        self.assertIsNone(report.problems[0].target)

    def test_cached_directories_do_not_cache_file_link_checks(self):
        self.destination.write_text('0' * 64 + ' *folder/second\n' + '0' * 64 + ' *folder/linked\n', encoding='utf-8')
        original = engine._inspect
        def inspect(path, info=None):
            if path == str(self.root / 'folder' / 'linked'):
                raise engine.LinkedPath('test reparse point')
            return original(path, info)
        with patch.object(engine, '_inspect', side_effect=inspect), patch.object(engine, 'hash_file', wraps=engine.hash_file) as hashing:
            report = engine.verify(str(self.destination), self.settings)
        self.assertEqual(1, hashing.call_count)
        self.assertEqual('Skipped: link', report.all_rows[1].status)
        self.assertIsNone(report.all_rows[1].target)

    def test_windows_and_unix_roundtrip_all_algorithms(self):
        import blake3
        chosen = (str(self.root / 'first'), str(self.root / 'folder'))
        with patch.object(engine, '_native_blake3', return_value=blake3.blake3):
            for algorithm in engine.ALGORITHMS:
                for unix in (False, True):
                    settings = engine.Settings(unix_format=unix)
                    path = self.root / ('generated-' + str(unix) + algorithm.extension)
                    with self.subTest(algorithm=algorithm.identifier, unix=unix):
                        result = engine.generate(str(self.root), chosen, str(path), algorithm, settings)
                        self.assertEqual(2, result.files)
                        report = engine.verify(str(path), settings)
                        self.assertEqual((True, 2, 0), (report.complete, report.matched, len(report.problems)))
                        self.assertEqual(not unix, path.read_bytes().startswith(b'\xef\xbb\xbf'))

    def test_sfv_first_filename_bom_character_is_not_a_file_bom(self):
        source = self.root / '\ufeffname'
        source.write_bytes(b'abc')
        for unix in (False, True):
            settings = engine.Settings(filename_encoding='utf-8', unix_format=unix)
            destination = self.root / ('bom-name-' + str(unix) + '.sfv')
            engine.generate(str(self.root), (str(source),), str(destination), engine.BY_ID['crc32'], settings)
            report = engine.verify(str(destination), settings)
            self.assertEqual(1, report.matched, report.problems)
            self.assertEqual('\ufeffname', report.all_rows[0].path)

    def test_manifest_mutation_marks_results_incomplete(self):
        self.destination.write_text(hashlib.sha256(b'abc').hexdigest() + ' *first\n', encoding='utf-8')
        def mutate(amount):
            with self.destination.open('ab') as output:
                output.write(b'invalid\n')
        report = engine.verify(str(self.destination), self.settings, progress=mutate)
        self.assertFalse(report.complete)
        self.assertIn('Manifest changed', report.reason)

    def test_failed_file_reads_are_included_in_byte_count(self):
        self.destination.write_text('0' * 64 + ' *first\n', encoding='utf-8')
        def partial_read(path, algorithm, settings, check, progress, state):
            progress(3)
            raise OSError('Interrupted read')
        with patch.object(engine, 'hash_file', side_effect=partial_read):
            report = engine.verify(str(self.destination), self.settings)
        self.assertEqual(3, report.bytes_read)
        self.assertEqual('Unreadable', report.problems[0].status)

    def test_extended_paths_are_idempotent(self):
        for path in ('C:\\folder\\file', '\\\\server\\share\\file'):
            converted = engine.native_path(path)
            self.assertTrue(converted.startswith('\\\\?\\'))
            self.assertEqual(converted, engine.native_path(converted))
            self.assertEqual(path, engine._logical(converted))

    def test_junction_is_skipped_without_traversing_target(self):
        import subprocess
        link = self.root / 'junction'
        completed = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(self.root / 'folder')], capture_output=True, text=True)
        if completed.returncode:
            self.skipTest('Directory junction creation unavailable: ' + completed.stderr)
        try:
            self.destination.write_text('0' * 64 + ' *junction/second\n', encoding='utf-8')
            report = engine.verify(str(self.destination), self.settings)
            self.assertEqual('Skipped: link', report.problems[0].status)
            with self.assertRaises(ValueError):
                engine.generate(str(self.root), (str(link / 'second'),), str(self.destination), self.algorithm, self.settings, expected_destination=engine._identity(self.destination.stat()))
            with self.assertRaises(engine.LinkedPath):
                engine.generate(str(self.root), (), str(link / 'output.sha256'), self.algorithm, self.settings)
            result = engine.generate(str(self.root), (), str(self.destination), self.algorithm, self.settings, expected_destination=engine._identity(self.destination.stat()))
            self.assertEqual(2, result.files)
            self.assertEqual(1, result.skipped)
        finally:
            os.rmdir(link)

    def test_navigated_junction_root_and_ancestor_are_supported(self):
        import subprocess
        target = self.root / 'folder'
        (target / 'nested').mkdir()
        (target / 'nested' / 'third').write_bytes(b'ghi')
        link = self.root / 'chosen'
        completed = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True, text=True)
        if completed.returncode:
            self.skipTest('Directory junction creation unavailable: ' + completed.stderr)
        try:
            for root, count in ((link, 2), (link / 'nested', 1)):
                destination = root / 'checks.sha256'
                with self.subTest(root=root):
                    result = engine.generate(str(root), (), str(destination), self.algorithm, self.settings)
                    self.assertEqual(count, result.files)
                    self.assertIn(str(destination), engine.discover(str(root)))
                    report = engine.verify(str(destination), self.settings)
                    self.assertEqual((True, count, 0), (report.complete, report.matched, len(report.problems)))
                    replaced = engine.generate(str(root), (), str(destination), self.algorithm, self.settings, expected_destination=engine._identity(destination.stat()))
                    self.assertEqual(count, replaced.files)
        finally:
            os.rmdir(link)


class ChecksumPackageTest(TestCase):
    def test_environment_and_lock_match_native_version(self):
        import build
        import yaml
        environment = yaml.safe_load((build.ROOT / 'environment.yml').read_text(encoding='utf-8'))
        lock = yaml.safe_load((build.ROOT / 'conda-lock.yml').read_text(encoding='utf-8'))
        self.assertIn('blake3=1.0.10', environment['dependencies'])
        self.assertEqual(['1.0.10'], [package['version'] for package in lock['package']
                                     if package['name'] == 'blake3' and package['platform'] == 'win-64'])

    def test_native_inputs_reject_wrong_version_corruption_and_missing_license(self):
        from src.main.resources.base.Plugins.ChecksumFiles import package
        with patch.object(package.importlib.metadata, 'distribution', return_value=Mock(version='1.0.9')):
            with self.assertRaisesRegex(ValueError, 'pinned BLAKE3'):
                package.native_files()
        with patch.object(package.Path, 'read_bytes', return_value=b'altered native artifact'):
            with self.assertRaisesRegex(ValueError, 'does not match'):
                package.native_files()
        with patch.object(package.Path, 'is_file', return_value=False):
            with self.assertRaisesRegex(ValueError, 'license is missing'):
                package.native_files()

    def test_spec_collects_plugin_defaults_native_binary_and_license(self):
        import build
        from runpy import run_path
        from PyInstaller.building.utils import format_binaries_and_datas
        with patch('PyInstaller.utils.hooks.collect_all', return_value=([], [], [])):
            specification = run_path(str(build.ROOT / 'application.spec'), init_globals={
                'SPECPATH': str(build.ROOT), 'Analysis': Mock(), 'PYZ': Mock(), 'EXE': Mock(), 'COLLECT': Mock()})
        datas = dict(format_binaries_and_datas(specification['datas'], workingdir=str(build.ROOT)))
        binaries = dict(format_binaries_and_datas(specification['binaries'], workingdir=str(build.ROOT)))
        root = Path('resources/Plugins/ChecksumFiles')
        for name in ('ChecksumFiles.json', 'checksum_files/__init__.py', 'checksum_files/commands.py', 'checksum_files/engine.py', 'README.md', 'checksum_files/_vendor/blake3/__init__.py', 'checksum_files/_vendor/blake3/LICENSE'):
            self.assertIn(str(root / name), datas)
        self.assertIn(str(root / 'checksum_files/_vendor/blake3/blake3.cp314-win_amd64.pyd'), binaries)

    def test_checksum_plugin_lives_in_bundled_resources(self):
        import build
        from fman.impl.plugins.discover import find_plugin_dirs
        plugins = build.ROOT / 'src/main/resources/base/Plugins'
        with TemporaryDirectory() as temporary:
            discovered = find_plugin_dirs(str(plugins), str(Path(temporary) / 'Third-party'), str(Path(temporary) / 'User'))
        self.assertIn(str(plugins / 'ChecksumFiles'), discovered)
        self.assertTrue((plugins / 'ChecksumFiles/checksum_files/__init__.py').is_file())

    def test_offline_package_hashes_licenses_and_refuses_overwrite(self):
        from src.main.resources.base.Plugins.ChecksumFiles.package import package
        with TemporaryDirectory() as directory:
            root = package(Path(directory) / 'ChecksumFiles')
            metadata = json.loads((root / 'package-manifest.json').read_text(encoding='utf-8'))
            for name, digest in metadata['files'].items():
                self.assertEqual(digest, hashlib.sha256((root / name).read_bytes()).hexdigest())
            self.assertEqual('cp314', metadata['python_abi'])
            self.assertTrue(metadata['origin'].startswith('Installed blake3 distribution;'))
            self.assertTrue((root / 'checksum_files/_vendor/blake3/LICENSE').is_file())
            with self.assertRaises(FileExistsError):
                package(root)


class ChecksumCommandTest(TestCase):
    def setUp(self):
        from fman.ui import UiOwner
        from checksum_files import commands
        self.commands = commands
        self.owner = UiOwner()
        self.addCleanup(self.owner.invalidate)
        self.previous_owner = commands.ChecksumController.owner
        commands.ChecksumController.owner = self.owner
        self.addCleanup(setattr, commands.ChecksumController, 'owner', self.previous_owner)
        self.pane = Mock()
        self.pane.get_path.return_value = 'file://C:/checks'
        self.pane.get_selected_files.return_value = []
        self.pane.get_file_under_cursor.return_value = None
        self.settings = patch.object(commands, 'load_json', return_value={})
        self.settings.start()
        self.addCleanup(self.settings.stop)

    def test_capture_uses_only_explicit_selection_and_detaches(self):
        with self.commands._running(self.pane) as run:
            root, selected, settings, highlighted = self.commands._capture(run, True)
        self.assertEqual((), selected)
        self.assertIsNone(highlighted)
        self.pane.get_file_under_cursor.assert_not_called()
        self.pane.on_path_changed.return_value.assert_called_once_with()
        self.pane.on_closed.return_value.assert_called_once_with()

    def test_command_aliases_are_iterable_from_pane_registry(self):
        from fman.impl.plugins.command_registry import PaneCommandRegistry
        registry = PaneCommandRegistry(Mock(), Mock())
        for name, command, title in (
            ('generate_checksum_file', self.commands.GenerateChecksumFile, 'Generate checksum file'),
            ('verify_checksum', self.commands.VerifyChecksum, 'Verify checksum file')):
            with self.subTest(command=name):
                registry.register_command(name, command)
                self.assertEqual((title,), tuple(registry.get_command_aliases(name)))

    def test_unstable_capture_is_rejected(self):
        self.pane.get_path.side_effect = ['file://C:/first', 'file://C:/second']
        with self.commands._running(self.pane) as run, self.assertRaises(ValueError):
            self.commands._capture(run, True)
        self.pane.on_path_changed.return_value.assert_called_once_with()

    def test_prompt_cancel_does_not_start_work(self):
        with patch.object(self.commands, 'show_quicksearch', return_value=('', 'sha256')), patch.object(self.commands, 'show_prompt', return_value=('', False)), patch.object(self.commands, 'submit_task') as submit:
            self.commands.GenerateChecksumFile(self.pane)()
        submit.assert_not_called()

    def test_suggested_filename_uses_folder_name_or_root_fallback(self):
        for url, expected in (('file://C:/checks', 'checks.sha256'), ('file://C:/', 'checksums.sha256'), ('file:////server/share/', 'checksums.sha256')):
            with self.subTest(url=url), patch.object(self.commands, 'show_quicksearch', return_value=('', 'sha256')), patch.object(self.commands, 'show_prompt', return_value=('', False)) as prompt, patch.object(self.commands, 'submit_task') as submit, patch.object(self.commands, 'show_alert') as alert:
                self.pane.get_path.return_value = url
                self.commands.GenerateChecksumFile(self.pane)()
                alert.assert_not_called()
                self.assertEqual(expected, prompt.call_args.args[1])
                submit.assert_not_called()

    def test_error_prefixes_match_palette_names(self):
        for command in (self.commands.GenerateChecksumFile, self.commands.VerifyChecksum):
            with self.subTest(command=command), patch.object(self.commands, '_capture', side_effect=ValueError('invalid request')), patch.object(self.commands, 'show_alert') as alert:
                command(self.pane)()
                alert.assert_called_once_with(command.aliases[0] + ': invalid request')

    def test_verification_without_manifests_ignores_marked_selection(self):
        with patch.object(self.commands.engine, 'discover', return_value=()), patch.object(self.commands, 'submit_task', side_effect=lambda task: task()), patch.object(self.commands, 'show_alert') as alert:
            self.commands.VerifyChecksum(self.pane)()
        alert.assert_called_once_with('No checksum file found in the current folder.')
        self.pane.get_selected_files.assert_not_called()
        self.pane.get_file_under_cursor.assert_called_once_with()

    def _verify_choice(self, manifests, highlighted, expected, result=None, after_capture=None):
        self.pane.get_file_under_cursor.return_value = highlighted
        self.pane.get_file_under_cursor.reset_mock()
        self.pane.get_selected_files.return_value = ['file://C:/checks/marked.md5']
        result = result if result is not None else engine.Results().freeze()
        with patch.object(engine, 'discover', return_value=manifests, side_effect=after_capture), patch.object(engine, 'verify', return_value=result) as verify, patch.object(self.commands, 'submit_task', side_effect=lambda task: task()), patch.object(self.commands, '_choose') as choose, patch.object(self.commands, 'show_results') as table, patch.object(self.commands, 'show_alert') as alert:
            self.commands.VerifyChecksum(self.pane)()
        alert.assert_not_called()
        choose.assert_not_called()
        verify.assert_called_once()
        self.assertEqual(expected, verify.call_args.args[0])
        self.assertIs(result, table.call_args.args[0])
        self.assertEqual(expected, table.call_args.args[2])
        self.assertNotIn(self.pane, self.commands._busy)
        self.pane.get_selected_files.assert_not_called()
        self.pane.get_file_under_cursor.assert_called_once_with()

    def test_verification_prefers_highlighted_supported_manifest(self):
        manifests = ('C:\\checks\\first.md5', 'C:\\checks\\selected.SHA3')
        self._verify_choice(manifests, 'file://C:/checks/selected.SHA3', manifests[1])

    def test_verification_falls_back_in_case_insensitive_filename_order(self):
        manifests = ('C:\\checks\\B.md5', 'C:\\checks\\a.sha256', 'C:\\checks\\0.xxh3')
        for highlighted in (None, 'file://C:/checks/ordinary.txt', 'file://C:/checks/0.xxh3',
                            'file://C:/checks/directory.sha256', 'file://C:/elsewhere/other.sha256'):
            with self.subTest(highlighted=highlighted):
                self._verify_choice(manifests, highlighted, manifests[1])

    def test_verification_order_has_a_deterministic_case_tiebreaker(self):
        manifests = ('C:\\checks\\a.sha256', 'C:\\checks\\A.sha256')
        self._verify_choice(manifests, None, manifests[1])
        self._verify_choice(tuple(reversed(manifests)), None, manifests[1])
        self._verify_choice(manifests, 'file://C:/checks/a.sha256', manifests[0])

    def test_verification_reuses_cursor_captured_before_discovery(self):
        manifests = ('C:\\checks\\first.md5', 'C:\\checks\\selected.sha256')
        def discover(root, check):
            self.pane.get_file_under_cursor.return_value = 'file://C:/checks/first.md5'
            return manifests
        self._verify_choice(manifests, 'file://C:/checks/selected.sha256', manifests[1], after_capture=discover)

    def test_verification_does_not_retry_an_incomplete_chosen_manifest(self):
        manifests = ('C:\\checks\\first.md5', 'C:\\checks\\broken.sha256')
        for reason in ('Permission denied.', 'Manifest changed while reading.', 'Malformed record.'):
            report = engine.Results()
            report.reason = reason
            self._verify_choice(manifests, 'file://C:/checks/broken.sha256', manifests[1], result=report.freeze())

    def test_verification_rejects_path_change_during_cursor_capture(self):
        def capture_cursor():
            self.pane.on_path_changed.call_args.args[0]()
            return 'file://C:/checks/first.md5'
        self.pane.get_file_under_cursor.side_effect = capture_cursor
        with patch.object(self.commands, 'submit_task') as submit, patch.object(self.commands, 'show_alert') as alert:
            self.commands.VerifyChecksum(self.pane)()
        submit.assert_not_called()
        self.assertIn('folder changed during capture', alert.call_args.args[0])
        self.pane.on_path_changed.return_value.assert_called_once_with()

    def test_verification_with_only_unsupported_manifests_alerts(self):
        with patch.object(engine, 'discover', return_value=('C:\\checks\\only.xxh3',)), patch.object(engine, 'verify') as verify, patch.object(self.commands, 'submit_task', side_effect=lambda task: task()), patch.object(self.commands, 'show_alert') as alert:
            self.commands.VerifyChecksum(self.pane)()
        alert.assert_called_once_with('No checksum file found in the current folder.')
        verify.assert_not_called()

    def test_owner_cancel_and_busy_guard(self):
        with self.commands._running(self.pane) as run:
            with self.assertRaises(ValueError), self.commands._running(self.pane):
                pass
            self.owner.invalidate()
            with self.assertRaises(engine.Canceled):
                run.check()
        self.assertNotIn(self.pane, self.commands._busy)

    def test_results_table_shows_all_retained_rows_modeless(self):
        results = engine.Results()
        results.add(engine.ResultRow(1, 'first', 'Matched', target='C:\\checks\\first'))
        results.add(engine.ResultRow(2, 'second', 'Mismatch', target='C:\\checks\\second'))
        results.complete = True
        frozen = results.freeze()
        with patch.object(self.commands, 'show_quick_table') as show, patch('builtins.open', side_effect=AssertionError('UI performed I/O')):
            self.commands.show_results(frozen, self.pane, 'C:\\checks\\checks.sha256')
        options = show.call_args.kwargs
        self.assertEqual(['first', 'second'], [row.cells[0] for row in options['rows']])
        self.assertIs(False, options['modal'])
        self.assertIs(self.pane, options['pane'])
        self.assertEqual('C:\\checks', options['base_path'])
        self.assertEqual(self.commands.VerifyChecksum.aliases[0] + ': checks.sha256', options['title'])
        self.assertEqual(frozen.summary, options['summary'])

    def test_results_navigate_to_verified_raw_paths_not_escaped_cells(self):
        from fman.impl.ui.table_data import TableSchema
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            target = folder / 'report\u200b.txt'
            target.write_bytes(b'payload')
            manifest = folder / 'checks.sha256'
            engine.generate(str(folder), (), str(manifest), engine.BY_ID['sha256'], engine.Settings())
            with open(manifest, 'ab') as stream:
                stream.write(b'not a checksum record\n')
            results = engine.verify(str(manifest), engine.Settings())
            with patch.object(self.commands, 'show_quick_table') as show:
                self.commands.show_results(results, self.pane, str(manifest))
            options = show.call_args.kwargs
            schema = TableSchema(self.commands.COLUMNS, options['base_path'])
            rows = {row.cells[1]: row for row in schema.snapshot(options['rows'])}
            matched, invalid = rows['Matched'], rows['Invalid record']
            self.assertEqual('report\\u200b.txt', matched.cells[0])
            self.assertEqual(str(target), schema.target(matched, 0))
            self.assertTrue(os.path.isfile(schema.target(matched, 0)))
            self.assertIsNone(schema.target(invalid, 0))

    def test_publication_notifies_even_if_owner_closes_after_commit(self):
        def submit(task):
            task.result = engine.GenerationResult(1, 3, 0)
            task.completed = True
            self.owner.invalidate()
        with patch.object(self.commands, 'show_quicksearch', return_value=('', 'sha256')), patch.object(self.commands, 'show_prompt', return_value=('CheckSum.sha256', True)), patch.object(engine, '_inspect', side_effect=FileNotFoundError), patch.object(self.commands, 'submit_task', side_effect=submit), patch.object(self.commands, 'notify_file_added') as notify, patch.object(self.commands, 'show_status_message') as status:
            self.commands.GenerateChecksumFile(self.pane)()
        notify.assert_called_once_with('file://C:/checks/CheckSum.sha256')
        status.assert_not_called()