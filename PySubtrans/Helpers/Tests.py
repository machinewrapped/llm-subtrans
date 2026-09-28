from collections.abc import Callable
import functools
import logging
import os
import sys
import tempfile
import unittest
from datetime import datetime
from typing import Any

from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleFormatRegistry import SubtitleFormatRegistry
from PySubtrans.Subtitles import Subtitles

separator = "".center(60, "-")
wide_separator = "".center(120, "-")

def log_info(text: str, prefix: str = ""):
    """
    Logs a string as individual lines with an optional prefix on each line using logging.info.
    """
    for line in text.strip().split("\n"):
        logging.info(f"{prefix}{line}")

def log_error(text: str, prefix: str = ""):
    """
    Logs a string as individual lines with an optional prefix on each line using logging.error.
    """
    for line in text.strip().split("\n"):
        logging.error(f"{prefix}{line}")

def log_test_name(test_name: str):
    """
    Logs the name of the test with a separator before and after.
    """
    logging.info(separator)
    log_info(test_name.center(len(separator)))
    logging.info(separator)

def log_expected_result(expected : Any, result : Any):
    """
    Logs the expected result and the actual result.
    """
    log_info(str(expected), prefix="===".ljust(10))
    log_info(str(result), prefix="-->".ljust(10))
    if expected != result:
        log_error("*** UNEXPECTED RESULT! ***", prefix="!!!".ljust(10))
    logging.info(separator)

def log_input_expected_result(input : Any, expected : Any, result : Any):
    """
    Logs the input value, the expected result and the actual result.
    """
    log_info(str(input), prefix="".ljust(10))
    log_info(str(expected), prefix="===".ljust(10))
    log_info(str(result), prefix="-->".ljust(10))
    if expected != result:
        log_error("*** UNEXPECTED RESULT! ***", prefix="!!!".ljust(10))
    logging.info(separator)

def log_input_expected_error(input : Any, expected_error : type[Exception], result : Any):
    """
    Logs the input value, the expected error and the actual error.
    """
    log_info(str(input), prefix="".ljust(10))
    log_info(expected_error.__name__, prefix="===".ljust(10))
    if not isinstance(result, expected_error):
        log_error("*** UNEXPECTED ERROR! ***", prefix="!!!".ljust(10))
    log_info(str(result), prefix="-->".ljust(10))
    logging.info(separator)


def skip_if_debugger_attached(test_method):
    """
    Decorator to skips a test method when debugger is attached.
    Use this to skip tests that raise expected exceptions when debugging,
    to facilitate debugging tests that are UNEXPECTEDLY raising exceptions.

    Usage:
        @skip_if_debugger_attached
        def test_some_exception_handling(self):
            # Test that raises exceptions
            pass
    """
    @functools.wraps(test_method)
    def wrapper(self, *args, **kwargs):
        if sys.gettrace() is not None:
            test_name = test_method.__name__
            logging.info(f"Skipped {test_name} when debugger is attached")
        else:
            return test_method(self, *args, **kwargs)
    return wrapper

def _mentions_temp_path(text : str, temp_root : str) -> bool:
    """
    Whether a traceback mentions the temporary directory.

    Tracebacks escape Windows path separators, so doubled backslashes are
    collapsed before comparing.
    """
    return temp_root.lower() in text.replace('\\\\', '\\').lower()

def DescribeBlockedTempFailures(result : unittest.TestResult) -> str|None:
    """
    Describe test errors caused by a file sandbox denying access to the temporary directory.

    A test that cannot create or clean up its temporary files never reaches its
    assertions, so these errors say nothing about the code under test. Reporting them
    separately stops them being read as regressions.

    Returns a message to log, or None when no error looks like a sandbox restriction.
    """
    if not result.errors:
        return None

    temp_root = tempfile.gettempdir()
    blocked = [
        (test, traceback) for test, traceback in result.errors
        if 'PermissionError' in traceback and _mentions_temp_path(traceback, temp_root)
    ]

    if not blocked:
        return None

    examples = ', '.join(test.id().split('.')[-1] for test, _traceback in blocked[:3])

    return (
        f"{len(blocked)} of {len(result.errors)} errors are PermissionError against the temporary directory:\n"
        f"  {temp_root}\n"
        "The tests could not create or clean up temporary files, so they never ran their assertions.\n"
        "This is almost always a file sandbox restriction rather than a code failure - re-run with\n"
        "unrestricted file access to verify them. Affected tests include: "
        f"{examples}"
    )

def ReportBlockedTempFailures(label : str, result : unittest.TestResult) -> bool:
    """
    Report any test errors caused by a file sandbox denying access to the temporary directory.

    Printed and logged, because a runner may only do one of the two. Returns True when
    such errors were found, so callers can qualify their own summary.
    """
    message = DescribeBlockedTempFailures(result)

    if not message:
        return False

    print(separator)
    print(f"{label}: {message}")
    print(separator)
    log_error(f"{label}: {message}")

    return True

def create_logfile(results_dir : str, log_name : str, log_level = logging.DEBUG) -> logging.FileHandler:
    """
    Creates a log file with the specified name in the specified directory and adds it to the root logger.
    """
    log_path = os.path.join(results_dir, log_name)
    file_handler = logging.FileHandler(log_path, encoding='utf-8', mode='w')
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    logging.getLogger('').addHandler(file_handler)
    return file_handler

def end_logfile(file_handler : logging.FileHandler):
    """
    Closes the file handler for the log file.
    """
    logging.getLogger('').removeHandler(file_handler)
    file_handler.close()

def _configure_base_logger(results_path, test_name):
    """
    Configures and returns a base logger that logs DEBUG messages to the console
    and to a general log file named after the test name.
    """
    logger = logging.getLogger(test_name)
    logger.setLevel(logging.DEBUG)

    test_log_path = os.path.join(results_path, f"{test_name}.log")
    file_handler = logging.FileHandler(test_log_path, mode='w', encoding='utf-8')
    file_formatter = logging.Formatter('%(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    return logger

def _add_test_file_logger(logger, results_path, input_filename, test_name):
    """
    Adds a file handler to log INFO level messages to a specific file named after the input file (without extension) and test name.
    """
    base_filename, dummy = os.path.splitext(input_filename) # type: ignore[ignore-unused]
    input_log_path = os.path.join(results_path, f"{base_filename}-{test_name}.log")
    file_handler = logging.FileHandler(input_log_path, mode='w', encoding='utf-8')
    file_formatter = logging.Formatter('%(message)s')
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    return file_handler

def RunTestOnAllSubtitleFiles(run_test : Callable, test_options: list[dict], directory_path: str, results_path: str|None = None):
    """
    Run a series of tests on all .srt files in the test_subtitles directory.
    """
    test_name = run_test.__name__

    results_path = results_path or directory_path
    os.makedirs(results_path, exist_ok=True)

    logger = _configure_base_logger(results_path, test_name)

    print(separator)
    print(f"Running {test_name}")

    logger.info(separator)
    logger.info(f"Running {test_name}")
    logger.info(separator)
    logger.info("")

    supported_formats = SubtitleFormatRegistry.enumerate_formats()

    def _is_supported_subtitle_file(f):
        file_path = os.path.join(directory_path, f)
        return (
            os.path.isfile(file_path)
            and SubtitleFormatRegistry.get_format_from_filename(f) in supported_formats
        )

    files = [f for f in os.listdir(directory_path) if _is_supported_subtitle_file(f)]
    print (f"Running {test_name} on {len(files)} files in {directory_path}...")

    for file in files:
        file_handler = _add_test_file_logger(logger, results_path, file, test_name)

        filepath = os.path.join(directory_path, file)

        current_time = datetime.now().strftime("%Y-%m-%d at %H:%M")
        logger.info(f"File: {filepath}")
        logger.info(f"Tested: {current_time}")
        logger.info(separator)

        try:
            subtitles = Subtitles(filepath)
            subtitles.LoadSubtitles()

            for options in test_options:
                logger.info("")
                run_test(subtitles, logger, SettingsType(options))

        except Exception as e:
            logger.error(f"Error processing {filepath}: {str(e)}")
            print(f"!!! ERROR RUNNING {test_name} ON {file} !!!")

        finally:
            logger.removeHandler(file_handler)


