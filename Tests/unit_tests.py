import logging
import os
import sys
import unittest

# Add the parent directory to the sys path so that modules can be found
base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(base_path)

from PySubtitle.Helpers.Tests import create_logfile

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
        # Change to base directory for discovery
        os.chdir(base_dir)
        
        # Discover tests in PySubtitle.UnitTests
        pysubtitle_dir = os.path.join(base_dir, 'PySubtitle', 'UnitTests')
        if os.path.exists(pysubtitle_dir):
            pysubtitle_tests = loader.discover(pysubtitle_dir, pattern='test_*.py', top_level_dir=base_dir)
        else:
            pysubtitle_tests = unittest.TestSuite()
        
        # Discover tests in GUI.UnitTests  
        gui_dir = os.path.join(base_dir, 'GUI', 'UnitTests')
        if os.path.exists(gui_dir):
            try:
                gui_tests = loader.discover(gui_dir, pattern='test_*.py', top_level_dir=base_dir)
            except (ImportError, ModuleNotFoundError):
                gui_tests = unittest.TestSuite()
        else:
            gui_tests = unittest.TestSuite()
    
    finally:
        # Restore original directory
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
    
