from importlib.machinery import ModuleSpec
import os
import logging
import importlib.util
import sys
import argparse
from datetime import datetime
from types import ModuleType
import unittest

# Add the parent directory to the sys path so that modules can be found
base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(base_path)

import PySubtitle.UnitTests
import GUI.UnitTests
from PySubtitle.Helpers.Tests import create_logfile, end_logfile, separator

logging.getLogger().setLevel(logging.DEBUG)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.WARNING)
console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))

def run_unit_tests(results_path : str):
    """
    Run all unit tests in PySubtitle.UnitTests and GUI.UnitTests.
    """
    log_file = create_logfile(results_path, "unit_tests.log")

    logging.info(separator)
    logging.info("Running unit tests at " + datetime.now().strftime("%Y-%m-%d at %H:%M"))
    logging.info(separator)

    # Run PySubtitle unit tests
    logging.info("Running PySubtitle unit tests...")
    unittest.runner.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(PySubtitle.UnitTests))

    # Run GUI unit tests
    logging.info("Running GUI unit tests...")
    unittest.runner.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(GUI.UnitTests))

    logging.info(separator)
    logging.info("Completed unit tests at " + datetime.now().strftime("%Y-%m-%d at %H:%M"))
    logging.info(separator)

    end_logfile(log_file)


def run_functional_tests(tests_directory, subtitles_directory, results_directory, test_name=None):
    """
    Scans the given directory for .py files, imports them, and runs the run_tests function if it exists.
    If a test_name is specified, only that test is run.
    :param tests_directory: Directory containing the test .py files.
    :param subtitles_directory: Path to test_subtitles subdirectory.
    :param test_name: Optional specific test to run.
    """
    # List all files in the tests directory
    for filename in os.listdir(tests_directory):
        if test_name and filename != f"{test_name}.py":
            continue

        if not filename.endswith('.py') or filename.startswith('__init__'):
            continue

        module_name = filename[:-3]  # Remove ".py" from filename to get module name

        # Create the absolute file path
        filepath = os.path.join(tests_directory, filename)

        # Load the module
        spec : ModuleSpec|None = importlib.util.spec_from_file_location(module_name, filepath)
        if spec is None or spec.loader is None:
            logging.error(f"Could not load module {module_name} from {filepath}")
            continue

        module : ModuleType = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Check if run_tests function exists
        if hasattr(module, 'run_tests'):
            try:
                module.run_tests(subtitles_directory, results_directory)

            except Exception as e:
                logging.error(f"Error running tests in {filename}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Python tests")
    parser.add_argument('test', nargs='?', help="Specify the name of a test file to run (without .py)", default=None)
    args = parser.parse_args()

    scripts_directory = os.path.dirname(os.path.abspath(__file__))
    root_directory = os.path.dirname(scripts_directory)
    tests_directory = os.path.join(root_directory, 'Tests')
    subtitles_directory = os.path.join(root_directory, 'test_subtitles')
    results_directory =  os.path.join(root_directory, 'test_results')
    test_name = args.test

    if not os.path.exists(results_directory):
        os.makedirs(results_directory)

    create_logfile(results_directory, "run_tests.log")

    run_unit_tests(results_directory)

    run_functional_tests(tests_directory, subtitles_directory, results_directory, test_name=test_name)
