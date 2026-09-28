from PySubtrans.Helpers import DescribeError, FormatNumberRanges
from PySubtrans.Helpers.TestCases import LoggedTestCase


class TestHelperFunctions(LoggedTestCase):
    """Test generic helper functions."""

    def test_FormatNumberRanges(self) -> None:
        test_cases = [
            ([], ""),
            ([7], "7"),
            ([1, 2, 3, 5, 6, 9], "1-3, 5-6, 9"),
            ([19, 1, 2, 2, 3, 30], "1-3, 19, 30"),
            ([3, 2, 1], "1-3"),
        ]

        for numbers, expected in test_cases:
            with self.subTest(numbers=numbers):
                result = FormatNumberRanges(numbers)
                self.assertLoggedEqual(
                    "format number ranges",
                    expected,
                    result,
                    input_value=numbers,
                )


class TestDescribeError(LoggedTestCase):
    """Exception descriptions must identify the cause, not just repeat a bare message."""

    def test_message_and_type_are_reported(self) -> None:
        description = DescribeError(ValueError("model not found"))

        self.assertLoggedEqual("type and message", "ValueError: model not found", description,
                               input_value="ValueError('model not found')")

    def test_type_is_used_when_the_message_is_empty(self) -> None:
        description = DescribeError(TimeoutError())

        self.assertLoggedEqual("type only", "TimeoutError", description, input_value="TimeoutError()")

    def test_none_describes_nothing(self) -> None:
        description = DescribeError(None)

        self.assertLoggedEqual("empty description", "", description, input_value=None)

