import unittest
from datetime import timedelta
from PySubtrans.Helpers.Tests import log_input_expected_error, log_input_expected_result, log_test_name
from PySubtrans.Helpers.Time import GetTimeDelta, TimedeltaToText

class TestTimeHelpers(unittest.TestCase):
    get_timedelta_cases = [
        (timedelta(hours=1, minutes=30, seconds=45), timedelta(hours=1, minutes=30, seconds=45)),
        ("01:30:45,000", timedelta(hours=1, minutes=30, seconds=45)),
        ("30:45,000", timedelta(hours=0, minutes=30, seconds=45)), # Without hours
        ("01:30:45", timedelta(hours=1, minutes=30, seconds=45, milliseconds=0)), # Without milliseconds
        ("30:45", timedelta(hours=0, minutes=30, seconds=45, milliseconds=0)), # Without hours and milliseconds
        ("45,250", timedelta(hours=0, minutes=0, seconds=45, milliseconds=250)), # Without hours and minutes
        ("01:30:45.123", timedelta(hours=1, minutes=30, seconds=45, milliseconds=123)),  # Non-standard milliseconds separator
        ("30:45.123", timedelta(hours=0, minutes=30, seconds=45, milliseconds=123)),  # Without hours, non-standard milliseconds separator
        ("01:30:45，123", timedelta(hours=1, minutes=30, seconds=45, milliseconds=123)),  # Full-width comma
        ("30:45．123", timedelta(hours=0, minutes=30, seconds=45, milliseconds=123)),  # Without hours, full-width period
        ("10:20:30,400,500", timedelta(hours=10, minutes=20, seconds=30, milliseconds=400)),
        ("100:20:30,400,500,600", timedelta(hours=100, minutes=20, seconds=30, milliseconds=400)),
        (None, None),
        ("invalid", ValueError),
    ]

    def test_GetTimeDelta(self):
        log_test_name("GetTimeDelta")
        for value, expected in self.get_timedelta_cases:
            with self.subTest(value=value):
                error_expected = (expected == ValueError)
                result = GetTimeDelta(value, raise_exception = not error_expected)
                if error_expected:
                    log_input_expected_error(value, expected, result)
                    self.assertIsInstance(result, ValueError)
                else:
                    log_input_expected_result(value, expected, result)
                    self.assertEqual(result, expected)

    timedelta_to_text_cases = [
        (timedelta(hours=2, minutes=34, seconds=56, microseconds=789000), "2:34:56,789", True),
        (timedelta(minutes=4, seconds=5, microseconds=0), "04:05,000", True),
        (timedelta(minutes=12, seconds=5, microseconds=0), "12:05,000", True),
        (timedelta(seconds=45, microseconds=200000), "45,200", True),
        (timedelta(seconds=5, microseconds=100000), "05,100", True),
        (timedelta(seconds=19, microseconds=10), "19,000", True),
        (timedelta(hours=13, minutes=0, seconds=0), "13:00:00,000", True),
        (timedelta(minutes=59, seconds=59), "59:59,000", True),
        (timedelta(seconds=1), "01,000", True),
        (timedelta(seconds=0), "00,000", True),
        (timedelta(microseconds=999000), "00,999", True),
        (timedelta(microseconds=999), "00,000", True),
        (-timedelta(hours=2, minutes=34, seconds=56, microseconds=789000), "-2:34:56,789", True),
        (-timedelta(minutes=4, seconds=5, microseconds=0), "-04:05,000", True),
        (-timedelta(seconds=45, microseconds=200000), "-45,200", True),
        (-timedelta(seconds=5, microseconds=100000), "-05,100", True),
        (-timedelta(milliseconds=500), "-00,500", True),
        (-timedelta(hours=13, minutes=0, seconds=0), "-13:00:00,000", True),
        (-timedelta(minutes=59, seconds=59), "-59:59,000", True),
        (-timedelta(seconds=1), "-01,000", True),
        (timedelta(hours=2, minutes=34, seconds=56, microseconds=789000), "2:34:56", False),
        (timedelta(minutes=4, seconds=5, microseconds=0), "04:05", False),
        (timedelta(seconds=45, microseconds=200000), "45", False),
        (timedelta(hours=13, minutes=0, seconds=0), "13:00:00", False),
        (timedelta(minutes=59, seconds=59), "59:59", False),
        (timedelta(seconds=1), "01", False),
        (timedelta(seconds=0), "00", False),
        (-timedelta(hours=2, minutes=34, seconds=56, microseconds=789000), "-2:34:56", False),
        (-timedelta(minutes=4, seconds=5, microseconds=0), "-04:05", False),
        (-timedelta(seconds=45, microseconds=200000), "-45", False),
        (-timedelta(hours=13, minutes=0, seconds=0), "-13:00:00", False),
        (-timedelta(minutes=59, seconds=59), "-59:59", False),
        (-timedelta(seconds=1), "-01", False),
        (-timedelta(milliseconds=500), "-00", False)
    ]

    def test_TimeDeltaToText(self):
        log_test_name("TimeDeltaToText")
        for value, expected, include_milliseconds in self.timedelta_to_text_cases:
            with self.subTest(value=value):
                result = TimedeltaToText(value, include_milliseconds=include_milliseconds)
                log_input_expected_result((value, include_milliseconds), expected, result)
                self.assertEqual(result, expected)

if __name__ == '__main__':
    unittest.main()