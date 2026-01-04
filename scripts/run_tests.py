import os
import logging
import importlib.util
import sys
import argparse
import json
import subprocess
from datetime import datetime
from types import ModuleType

import unittest

base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, base_path)

from PySubtrans.Helpers.Tests import create_logfile, end_logfile, separator
from tests.unit_tests import discover_tests

total_run = 0
total_failures = 0
total_errors = 0
total_skipped = 0

summary_lines = [
    "Test Summary:"
]

def format_summary_line(label: str, run: int, failures: int, errors: int, skipped: int, ok: bool) -> str:
    return f"  {label:<12}: run: {run:>3} failures: {failures:>3} errors: {errors:>3} skipped: {skipped:>3} status={'OK ' if ok else 'FAIL'}"

logging.getLogger().setLevel(logging.INFO)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.WARNING)  # Only show warnings and above on console
console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
# Ensure the console handler is attached (it wasn't previously, so messages at WARNING+ were not visible)
if console_handler not in logging.getLogger().handlers:
    logging.getLogger().addHandler(console_handler)

def _check_pyright_available() -> bool:
    """Check if pyright is available in the current Python environment."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pyright", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False

def _run_pyright(base_path: str) -> tuple[bool, dict|None]:
    """Run pyright and return (success, json_result)."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pyright", "--outputjson", base_path],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes
            cwd=base_path
        )

        json_output = json.loads(result.stdout)
        logging.debug("Pyright output:")
        logging.debug(result.stdout)

        return (True, json_output)

    except subprocess.TimeoutExpired:
        logging.error("Pyright execution timed out after 5 minutes")
        return (False, None)
    except json.JSONDecodeError as e:
        logging.error(f"Failed to parse pyright JSON output: {e}")
        return (False, None)
    except Exception as e:
        logging.error(f"Error running pyright: {e}")
        return (False, None)

def _parse_pyright_results(json_output: dict) -> dict:
    """Extract metrics from pyright JSON output."""
    summary = json_output.get('summary', {})

    errors = summary.get('errorCount', 0)
    warnings = summary.get('warningCount', 0)
    files_analyzed = summary.get('filesAnalyzed', 0)

    return {
        'files_analyzed': files_analyzed,
        'errors': errors,
        'warnings': warnings,
        'ok': (errors == 0)
    }

def _log_pyright_diagnostics(json_output: dict, max_errors: int = 20):
    """Log detailed diagnostics from pyright output, limited to first N errors."""
    diagnostics = json_output.get('generalDiagnostics', [])

    if not diagnostics:
        logging.info("No type errors found")
        return

    for diag in diagnostics[:max_errors]:
        severity = diag.get('severity', 'unknown')
        file_path = diag.get('file', 'unknown')
        message = diag.get('message', 'unknown error')
        line = diag.get('range', {}).get('start', {}).get('line', 0) + 1

        log_msg = f"  {file_path}:{line} - {severity}: {message}"

        if severity == 'error':
            logging.error(log_msg)
        elif severity == 'warning':
            logging.warning(log_msg)
        else:
            logging.info(log_msg)

    if len(diagnostics) > max_errors:
        remaining = len(diagnostics) - max_errors
        logging.info(f"  ... and {remaining} more diagnostic messages (see full log)")

def run_type_checking(results_path: str) -> bool:
    """Run pyright type checking on the codebase.

    Checks if pyright is available, runs type checking if found, and reports
    results. Returns True if type checking passed (or was skipped), else False.
    """
    log_file = create_logfile(results_path, "type_checking.log")

    start_stamp = datetime.now().strftime("%Y-%m-%d at %H:%M")
    logging.info(separator)
    logging.info("Running type checking at " + start_stamp)
    logging.info(separator)

    # Check if pyright is available
    if not _check_pyright_available():
        logging.warning("Pyright is not available - skipping type checking")
        logging.info("To enable type checking, install pyright: pip install pyright")
        logging.info(separator)
        end_logfile(log_file)

        summary_lines.append("  Type Check : SKIPPED (pyright not available)")
        return True

    logging.info("Pyright is available, running type check...")

    # Run pyright
    success, json_output = _run_pyright(base_path)

    if not success or json_output is None:
        logging.error("Failed to run pyright type checking")
        end_stamp = datetime.now().strftime("%Y-%m-%d at %H:%M")
        logging.info(separator)
        logging.error("Type checking failed to execute at " + end_stamp)
        logging.info(separator)
        end_logfile(log_file)

        summary_lines.append("  Type Check : ERROR (execution failed)")
        return False

    # Parse results
    results = _parse_pyright_results(json_output)

    # Log summary
    logging.info(f"Files analyzed: {results['files_analyzed']}")
    logging.info(f"Errors: {results['errors']}")
    logging.info(f"Warnings: {results['warnings']}")

    # Log detailed diagnostics
    if results['errors'] > 0 or results['warnings'] > 0:
        logging.info(separator)
        logging.info("Diagnostic messages:")
        _log_pyright_diagnostics(json_output)

    # Update global counters
    global total_run, total_errors
    total_run += results['files_analyzed']
    total_errors += results['errors']

    # Add to summary
    summary_lines.append(
        format_summary_line(
            'Type Check',
            results['files_analyzed'],
            0,  # failures
            results['errors'],
            0,  # skipped
            results['ok']
        )
    )

    if results['warnings'] > 0:
        summary_lines.append(f"             (with {results['warnings']} warnings)")

    end_stamp = datetime.now().strftime("%Y-%m-%d at %H:%M")
    logging.info(separator)
    if results['ok']:
        logging.info("Completed type checking successfully at " + end_stamp)
    else:
        logging.error("Completed type checking with errors at " + end_stamp)
    logging.info(separator)

    end_logfile(log_file)
    return results['ok']

def run_unit_tests(results_path: str) -> bool:
    """Run all unit tests in PySubtrans.UnitTests and GuiSubtrans.UnitTests.

    Executes the two logical suites separately so we always see both sets of
    results even if the first has failures. Returns True if all tests across
    both suites succeeded, else False.
    """
    log_file = create_logfile(results_path, "unit_tests.log")

    start_stamp = datetime.now().strftime("%Y-%m-%d at %H:%M")
    logging.info(separator)
    logging.info("Running unit tests at " + start_stamp)
    logging.info(separator)

    runner = unittest.runner.TextTestRunner(verbosity=1)
    
    py_tests, gui_tests = discover_tests(base_path, separate_suites=True)
    
    logging.info("Running PySubtrans unit tests...")
    py_result = runner.run(py_tests)

    logging.info("Running GuiSubtrans unit tests...")
    gui_result = runner.run(gui_tests)

    def summarize(label: str, result: unittest.TestResult) -> dict:
        return {
            'label': label,
            'run': result.testsRun,
            'failures': len(result.failures),
            'errors': len(result.errors),
            'skipped': len(result.skipped) if hasattr(result, 'skipped') else 0,
            'ok': result.wasSuccessful()
        }


    global total_run, total_failures, total_errors, total_skipped
    py_summary = summarize('PySubtrans', py_result)
    gui_summary = summarize('GuiSubtrans', gui_result)

    total_run = py_summary['run'] + gui_summary['run']
    total_failures = py_summary['failures'] + gui_summary['failures']
    total_errors = py_summary['errors'] + gui_summary['errors']
    total_skipped = py_summary['skipped'] + gui_summary['skipped']
    overall_success = (total_failures == 0 and total_errors == 0)

    summary_lines.extend([
        format_summary_line('PySubtrans', py_summary['run'], py_summary['failures'], py_summary['errors'], py_summary['skipped'], py_summary['ok']),
        format_summary_line('GuiSubtrans', gui_summary['run'], gui_summary['failures'], gui_summary['errors'], gui_summary['skipped'], gui_summary['ok'])
    ])

    end_stamp = datetime.now().strftime("%Y-%m-%d at %H:%M")
    logging.info(separator)
    if overall_success:
        logging.info("Completed unit tests successfully at " + end_stamp)
    else:
        logging.error("Completed unit tests with failures at " + end_stamp)
    logging.info(separator)

    end_logfile(log_file)
    return overall_success


def run_functional_tests(tests_directory, subtitles_directory, results_directory, test_name=None):
    """
    Scans the given directory for .py files, imports them, and runs the run_tests function if it exists.
    If a test_name is specified, only that test is run.
    :param tests_directory: Directory containing the test .py files.
    :param subtitles_directory: Path to test_subtitles subdirectory.
    :param test_name: Optional specific test to run.
    """
    global total_run, total_failures
    test_files_run = 0
    test_files_failed = 0
    for filename in os.listdir(tests_directory):
        if test_name and filename != f"{test_name}.py":
            continue

        if not filename.endswith('.py') or filename.startswith('__init__'):
            continue

        module_name = filename[:-3]  # Remove ".py" from filename to get module name

        filepath = os.path.join(tests_directory, filename)

        spec = importlib.util.spec_from_file_location(module_name, filepath)
        if spec is None or spec.loader is None:
            logging.error(f"Could not load module {module_name} from {filepath}")
            continue

        module : ModuleType = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if hasattr(module, 'run_tests'):
            test_files_run += 1
            try:
                module.run_tests(subtitles_directory, results_directory)
            except Exception as e:
                logging.error(f"Error running tests in {filename}: {e}")
                summary_lines.append(f"Tests in {filename} failed")
                test_files_failed += 1

    if test_files_run > 0:
        summary_lines.append(format_summary_line('Functional', test_files_run, test_files_failed, 0, 0, test_files_failed == 0))

        total_run += test_files_run
        total_failures += test_files_failed

    return test_files_run, test_files_failed

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Python tests")
    parser.add_argument('test', nargs='?', help="Specify the name of a test file to run (without .py)", default=None)
    args = parser.parse_args()

    scripts_directory = os.path.dirname(os.path.abspath(__file__))
    root_directory = os.path.dirname(scripts_directory)
    tests_directory = os.path.join(root_directory, 'tests', 'functional')
    subtitles_directory = os.path.join(root_directory, 'test_subtitles')
    results_directory =  os.path.join(root_directory, 'test_results')
    test_name = args.test

    if not os.path.exists(results_directory):
        os.makedirs(results_directory)

    create_logfile(results_directory, "run_tests.log")

    # Run type checking first (fail fast on type errors)
    overall_success : bool = run_type_checking(results_directory)

    # Only run unit tests if type checking passed
    if overall_success:
        overall_success = run_unit_tests(results_directory)

    # Only run functional tests if unit tests passed
    if overall_success:
        func_run, func_failed = run_functional_tests(tests_directory, subtitles_directory, results_directory, test_name=test_name)
        overall_success = (func_failed == 0)

    summary_lines.append(format_summary_line('Overall', total_run, total_failures, total_errors, total_skipped, overall_success) + f" => {'SUCCESS' if overall_success else 'FAILED'}")

    # Always surface summary lines to console: print when successful, since we don't log INFO to console, but ERROR when failed
    for line in summary_lines:
        if overall_success:
            print(line)
        else:
            logging.error(line)

    if not overall_success:
        print("*************************************************")
        print("*******     One or more tests failed!    ********")
        print("*************************************************")
        sys.exit(1)
