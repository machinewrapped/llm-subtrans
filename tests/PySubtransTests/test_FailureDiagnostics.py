"""Reporting of environmental test failures caused by a sandbox blocking the temp directory."""
import tempfile
import unittest

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import DescribeBlockedTempFailures


class TestBlockedTempFailureReporting(LoggedTestCase):
    """Sandbox temp-directory failures must be reported as environmental, not as regressions."""

    def _result_with_errors(self, *tracebacks : str) -> unittest.TestResult:
        result = unittest.TestResult()
        test = unittest.TestCase('run')

        for traceback in tracebacks:
            result.errors.append((test, traceback))

        return result

    def _temp_permission_traceback(self) -> str:
        """A traceback shaped like unittest reports it, with escaped Windows separators."""
        escaped = tempfile.gettempdir().replace('\\', '\\\\')

        return (
            "Traceback (most recent call last):\n"
            "  File \"test.py\", line 38, in setUp\n"
            f"PermissionError: [Errno 13] Permission denied: '{escaped}\\\\tmp1234\\\\test.srt'"
        )

    def test_temp_permission_error_is_described(self) -> None:
        """A PermissionError against the temp directory is reported as a sandbox restriction."""
        message = DescribeBlockedTempFailures(self._result_with_errors(self._temp_permission_traceback()))

        self.assertLoggedIsNotNone("message produced", message)
        if message:
            self.assertLoggedIn("error count reported", "1 of 1", message)
            self.assertLoggedIn("temp directory reported", tempfile.gettempdir(), message)

    def test_unrelated_error_is_not_described(self) -> None:
        """An ordinary failure is left to speak for itself."""
        result = self._result_with_errors("Traceback (most recent call last):\nAssertionError: nope")

        self.assertLoggedIsNone("no sandbox message", DescribeBlockedTempFailures(result))

    def test_permission_error_outside_temp_is_not_described(self) -> None:
        """A permission error elsewhere is not attributed to the sandbox."""
        result = self._result_with_errors(
            "Traceback (most recent call last):\n"
            "PermissionError: [Errno 13] Permission denied: 'C:\\\\project\\\\subtitle.srt'")

        self.assertLoggedIsNone("not attributed to the sandbox", DescribeBlockedTempFailures(result))

    def test_no_errors_produce_no_message(self) -> None:
        """A clean result has nothing to explain."""
        self.assertLoggedIsNone("no message", DescribeBlockedTempFailures(unittest.TestResult()))
