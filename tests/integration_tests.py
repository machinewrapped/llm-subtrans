"""Run optional SDK and real media integration checks separately from unit tests."""
import importlib
import logging
import os
import sys
import unittest
from pathlib import Path


class GuiDependenciesUnavailable(unittest.TestCase):
    """Report optional GUI integration coverage that could not run."""

    def runTest(self) -> None:
        self.skipTest('PySide6 GUI dependencies are unavailable')


def Main() -> int:
    """Discover integration tests and return failure status to release scripts."""
    root = Path(__file__).resolve().parent.parent
    # Prefer this checkout over an editable installation in another worktree.
    sys.path.insert(0, str(root))
    results = root / 'test_results'
    results.mkdir(exist_ok=True)
    logging.basicConfig(filename=results / 'integration_tests.log', filemode='w',
                        encoding='utf-8', level=logging.INFO)
    suite = unittest.TestLoader().discover(
        str(root / 'tests' / 'IntegrationTests'), pattern='test_*.py', top_level_dir=str(root))
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    try:
        importlib.import_module('PySide6.QtGui')
        importlib.import_module('PySide6.QtWidgets')
    except (ImportError, OSError) as error:
        logging.info('Skipping GUI integration tests: %s', error)
        suite.addTest(GuiDependenciesUnavailable())
    else:
        suite.addTests(unittest.TestLoader().discover(
            str(root / 'tests' / 'GuiIntegrationTests'), pattern='test_*.py', top_level_dir=str(root)))
    if suite.countTestCases() == 0:
        print('No integration tests discovered.', file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(Main())
