"""Run optional SDK and real media integration checks separately from unit tests."""
import logging
import sys
import unittest
from pathlib import Path


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
    if suite.countTestCases() == 0:
        print('No integration tests discovered.', file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(Main())
