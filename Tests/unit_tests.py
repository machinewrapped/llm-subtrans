import logging
import os
import unittest

from PySubtitle.Helpers.Tests import create_logfile

def discover_tests_in_directory(loader : unittest.TestLoader, test_dir : str, base_dir : str, handle_import_errors : bool = False) -> unittest.TestSuite:
    """Discover tests in a specific directory with optional error handling."""
    if not os.path.exists(test_dir):
        return unittest.TestSuite()
    
    if handle_import_errors:
        try:
            return loader.discover(test_dir, pattern='test_*.py', top_level_dir=base_dir)
        except (ImportError, ModuleNotFoundError):
            return unittest.TestSuite()
    else:
        return loader.discover(test_dir, pattern='test_*.py', top_level_dir=base_dir)

def discover_tests(base_dir=None, separate_suites=False):
    """Automatically discover all test modules following naming conventions.
    
    Args:
        base_dir: Base directory to search from. If None, uses parent of this file.
        separate_suites: If True, returns (pysubtitle_suite, gui_suite). If False, returns combined suite.
    """
    if base_dir is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    loader = unittest.TestLoader()
    original_dir = os.getcwd()
    
    try:
        os.chdir(base_dir)
        
        pysubtitle_dir = os.path.join(base_dir, 'PySubtitle', 'UnitTests')
        pysubtitle_tests = discover_tests_in_directory(loader, pysubtitle_dir, base_dir)
        
        gui_dir = os.path.join(base_dir, 'GUI', 'UnitTests')
        gui_tests = discover_tests_in_directory(loader, gui_dir, base_dir, handle_import_errors=True)
    
    finally:
        os.chdir(original_dir)
    
    if separate_suites:
        return pysubtitle_tests, gui_tests
    else:
        combined_suite = unittest.TestSuite()
        combined_suite.addTest(gui_tests)
        combined_suite.addTest(pysubtitle_tests)
        return combined_suite

if __name__ == '__main__':
    scripts_directory = os.path.dirname(os.path.abspath(__file__))
    root_directory = os.path.dirname(scripts_directory)
    results_directory = os.path.join(root_directory, 'test_results')

    if not os.path.exists(results_directory):
        os.makedirs(results_directory)

    logging.getLogger().setLevel(logging.INFO)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))

    create_logfile(results_directory, "unit_tests.log")

    # Run discovered tests
    runner = unittest.TextTestRunner(verbosity=1)
    test_suite = discover_tests()
    for test in test_suite:
        result = runner.run(test)
        if not result.wasSuccessful():
            print("Some tests failed or had errors.")
            sys.exit(1)
    
