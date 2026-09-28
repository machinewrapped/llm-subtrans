"""Run optional SDK and real media integration checks separately from unit tests."""
import importlib
import logging
import sys
import unittest
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
# Prefer this checkout over an editable installation in another worktree.
sys.path.insert(0, str(_root))

from PySubtrans.Helpers.ImportGuard import CaptureOriginalImport
from PySubtrans.Helpers.Tests import ReportBlockedTempFailures
from tests.GuiTestSupport import ConfigureOffscreenPlatform

# Must happen before PySide6 is imported anywhere in this process; see PySubtrans.Helpers.ImportGuard.
CaptureOriginalImport()


def _discover(directory : str) -> unittest.TestSuite:
    """Discover every test_*.py under tests/<directory>."""
    return unittest.TestLoader().discover(
        str(_root / 'tests' / directory), pattern='test_*.py', top_level_dir=str(_root))


def _report_suite(label : str, counts : str) -> None:
    """Print a machine-readable suite result for scripts/run_tests.py to collect."""
    print(f"SUITE RESULT: {label} | {counts}", flush=True)


def _run(suite : unittest.TestSuite, label : str) -> bool:
    result = unittest.TextTestRunner(verbosity=1).run(suite)

    # Distinguish environmental failures before they are read as regressions
    ReportBlockedTempFailures(label, result)

    _report_suite(label, f"run={result.testsRun} failures={len(result.failures)} "
                         f"errors={len(result.errors)} skipped={len(result.skipped)}")

    return result.wasSuccessful()


def _gui_dependencies_available() -> bool:
    """Whether PySide6 can actually be imported, not just whether it's installed."""
    try:
        importlib.import_module('PySide6.QtGui')
        importlib.import_module('PySide6.QtWidgets')
    except (ImportError, OSError) as error:
        logging.info('Skipping GUI integration tests: %s', error)
        return False
    return True


def Main() -> int:
    """Run the non-GUI and GUI integration suites in turn and return combined status."""
    results = _root / 'test_results'
    results.mkdir(exist_ok=True)
    logging.basicConfig(filename=results / 'integration_tests.log', filemode='w',
                        encoding='utf-8', level=logging.INFO)

    non_gui_suite = _discover('IntegrationTests')
    if non_gui_suite.countTestCases() == 0:
        print('No integration tests discovered.', file=sys.stderr)
        return 1
    non_gui_ok = _run(non_gui_suite, 'Integration')

    # GUI tests run last: a nicer default ordering (the heavier, more fragile
    # suite trails the faster one), not a requirement for correctness -- the
    # import-hook corruption this used to guard against is now handled by
    # ImportGuard, scoped to the exact call site that needs it.
    ConfigureOffscreenPlatform()
    if _gui_dependencies_available():
        gui_ok = _run(_discover('GuiIntegrationTests'), 'GUI Integration')
    else:
        print('Skipping GUI integration tests: PySide6 dependencies are unavailable.', file=sys.stderr)
        _report_suite('GUI Integration', 'skipped')
        gui_ok = True

    return 0 if non_gui_ok and gui_ok else 1


if __name__ == '__main__':
    sys.exit(Main())
