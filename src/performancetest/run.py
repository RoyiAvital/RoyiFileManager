"""Launch performance workloads explicitly, outside verification discovery."""

import argparse
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
WORKLOADS = {
	'measure': (str(ROOT / 'src/misc/performance_report.py'),),
	'suite': ('-m', 'fman_performancetest.suite'),
	'search': ('-m', 'fman_performancetest.filter_find'),
	'pane': ('-m', 'fman_performancetest.pane_rendering_benchmark'),
	'legacy-search': ('-m', 'unittest', 'fman_performancetest.legacy.SearchPerformanceTest'),
	'legacy-metadata': ('-m', 'unittest', 'fman_performancetest.legacy.SearchMetadataPerformanceTest'),
	'image': ('-m', 'unittest', 'fman_performancetest.legacy.ImageMemoryTest'),
	'fd': ('-m', 'unittest', 'fman_performancetest.legacy.FindFilesPerformance.test_large_tree_exact_count_and_bounded_storage'),
	'poc': ('-m', 'unittest', 'fman_performancetest.legacy.TimingTest'),
	'pane-filter': ('-m', 'unittest', 'fman_performancetest.legacy.PaneFilterPerformance.test_full_update_performance'),
	'ui-table': ('-m', 'unittest', 'fman_performancetest.legacy.TablePerformance.test_large_snapshot_projection_timing'),
	'archive-copy': ('-m', 'unittest', 'fman_performancetest.legacy.ArchivePerformance.test_copy_verification_timing'),
	'archive-move': ('-m', 'unittest', 'fman_performancetest.legacy.ArchivePerformance.test_multi_item_move_verification_cost'),
}


def main(argv=None):
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('workload', choices=WORKLOADS)
	parser.add_argument('arguments', nargs=argparse.REMAINDER)
	args = parser.parse_args(argv)
	sys.path.insert(0, str(ROOT))
	import build
	environment = build._environment()
	environment['PYTHONPATH'] = os.pathsep.join((str(ROOT / 'src/performancetest/python'), environment['PYTHONPATH']))
	environment.setdefault('QT_QPA_PLATFORM', 'windows' if sys.platform == 'win32' else 'offscreen')
	if sys.platform == 'win32':
		environment['QT_QPA_FONTDIR'] = str(Path(os.environ['WINDIR']) / 'Fonts')
	return subprocess.run([sys.executable, *WORKLOADS[args.workload], *args.arguments],
		cwd=ROOT, env=environment).returncode


if __name__ == '__main__':
	sys.exit(main())