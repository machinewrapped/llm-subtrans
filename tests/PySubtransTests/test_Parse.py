import unittest
from enum import Enum

from PySubtrans.Helpers import GetValueName, GetValueFromName
from PySubtrans.Helpers.Parse import FormatKeyValuePairs, ParseDelayFromHeader, ParseKeyValuePairs, ParseNames, TryParseFloat, TryParseNonNegative
from PySubtrans.Helpers.TestCases import LoggedTestCase


class TestTryParseFloat(LoggedTestCase):
    def test_valid_numbers(self):
        """Numbers, numeric strings and exponents parse without raising."""
        cases = [
            (5, 5.0),
            (2.5, 2.5),
            ("3.25", 3.25),
            ("  7  ", 7.0),
            ("-1.5", -1.5),
            ("1e3", 1000.0),
            (True, None),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertLoggedEqual(f"float from {value!r}", expected, TryParseFloat(value),
                                       input_value=value)

    def test_invalid_numbers(self):
        """Missing and sloppy values return None instead of raising."""
        for value in (None, "", "   ", "soon", "12x", "nan-ish", object()):
            with self.subTest(value=value):
                self.assertLoggedEqual(f"float from {value!r}", None, TryParseFloat(value),
                                       input_value=value)


class TestTryParseNonNegative(LoggedTestCase):
    def test_positive_values(self):
        """Positive numbers pass through unchanged."""
        cases = [
            (5, 5.0),
            (2.5, 2.5),
            ("3.25", 3.25),
            ("  7  ", 7.0),
            ("1e3", 1000.0),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertLoggedEqual(f"non-negative from {value!r}", expected,
                                       TryParseNonNegative(value), input_value=value)

    def test_negative_values_clamped(self):
        """Negative numbers are clamped to zero."""
        for value in (-1.5, "-3", -0.001):
            with self.subTest(value=value):
                self.assertLoggedEqual(f"clamped from {value!r}", 0.0,
                                       TryParseNonNegative(value), input_value=value)

    def test_invalid_values(self):
        """Missing and non-numeric values return None."""
        for value in (None, "", "   ", "soon", True, object()):
            with self.subTest(value=value):
                self.assertLoggedEqual(f"non-negative from {value!r}", None,
                                       TryParseNonNegative(value), input_value=value)


class TestParseDelayFromHeader(LoggedTestCase):
    test_cases = [
        ("5", 5.0),
        ("10s", 10.0),
        ("5m", 300.0),
        ("500ms", 1.0),
        ("1500ms", 1.5),
        ("abc", 32.1),
    ]

    def test_ParseDelayFromHeader(self):
        for value, expected in self.test_cases:
            with self.subTest(value=value):
                result = ParseDelayFromHeader(value)
                self.assertLoggedEqual(f"delay parsed from {value}", expected, result, input_value=value)


class TestParseNames(LoggedTestCase):
    test_cases = [
        ("John, Jane, Alice", ["John", "Jane", "Alice"]),
        (["John", "Jane", "Alice"], ["John", "Jane", "Alice"]),
        ("Mike, Murray, Mabel, Marge", ["Mike", "Murray", "Mabel", "Marge"]),
        ("", []),
        ([] , []),
        ([""], [])
    ]

    def test_ParseNames(self):
        for value, expected in self.test_cases:
            with self.subTest(value=value):
                result = ParseNames(value)
                self.assertLoggedSequenceEqual(
                    f"names parsed from {value}",
                    expected,
                    result,
                    input_value=value,
                )

class TestParseValues(LoggedTestCase):
    class TestEnum(Enum):
        Test1 = 1
        Test2 = 2
        TestValue = 4
        TestExample = 5

    class TestObject:
        def __init__(self, name):
            self.name = name

    get_value_name_cases = [
        (12345, "12345"),
        (True, "True"),
        ("Test", "Test"),
        ("TEST", "TEST"),
        ("TestName", "TestName"),
        (TestEnum.Test1, "Test1"),
        (TestEnum.Test2, "Test2"),
        (TestEnum.TestValue, "Test Value"),
        (TestEnum.TestExample, "Test Example"),
        (TestObject("Test Object"), "Test Object")
    ]

    def test_GetValueName(self):
        for value, expected in self.get_value_name_cases:
            with self.subTest(value=value):
                result = GetValueName(value)
                self.assertLoggedEqual(f"name for {value}", expected, result, input_value=value)

    get_value_from_name_cases = [
        ("Test Name", ["Test Name", "Another Name", "Yet Another Name"], None, "Test Name"),
        ("Nonexistent Name", ["Test Name", "Another Name", "Yet Another Name"], "Default Value", "Default Value"),
        (34567, [12345, 34567, 98765], None, 34567),
        ("12345", [12345, 34567, 98765], None, 12345),
        ("Test2", TestEnum, None, TestEnum.Test2)
    ]

    def test_GetValueFromName(self):
        for value, names, default, expected in self.get_value_from_name_cases:
            with self.subTest(value=value):
                result = GetValueFromName(value, names, default)
                self.assertLoggedEqual(
                    "value from name",
                    expected,
                    result,
                    input_value=(value, names, default),
                )

class TestParseKeyValuePairs(LoggedTestCase):
    parse_cases = [
        ("Dragon::Drache\nHero::Held", {"Dragon": "Drache", "Hero": "Held"}),
        ("Dragon::Drache", {"Dragon": "Drache"}),
        ("", {}),
        (None, {}),
        ("MissingSeparator", {}),
        ("Key::Value::Extra", {"Key": "Value::Extra"}),
        ({"Dragon": "Drache"}, {"Dragon": "Drache"}),
        (["Dragon::Drache", "Hero::Held"], {"Dragon": "Drache", "Hero": "Held"}),
        ("  Dragon  ::  Drache  ", {"Dragon": "Drache"}),
    ]

    def test_ParseKeyValuePairs(self):
        for value, expected in self.parse_cases:
            with self.subTest(value=value):
                result = ParseKeyValuePairs(value)
                self.assertLoggedEqual("parsed key-value pairs", expected, result, input_value=value)


class TestFormatKeyValuePairs(LoggedTestCase):
    format_cases = [
        ({"Dragon": "Drache", "Hero": "Held"}, ["Dragon::Drache", "Hero::Held"]),
        ({"Single": "Term"}, ["Single::Term"]),
        ({}, []),
        (None, []),
    ]

    def test_FormatKeyValuePairs(self):
        for value, expected_lines in self.format_cases:
            with self.subTest(value=value):
                result = FormatKeyValuePairs(value)
                result_lines = result.splitlines() if result else []
                self.assertLoggedSequenceEqual("formatted key-value lines", expected_lines, result_lines, input_value=value)

    def test_RoundTrip(self):
        original = {"Dragon": "Drache", "Hero": "Held", "Magic Sword": "Zauberschwert"}
        formatted = FormatKeyValuePairs(original)
        parsed = ParseKeyValuePairs(formatted)
        self.assertLoggedEqual("round-trip key-value pairs", original, parsed)


if __name__ == '__main__':
    unittest.main()
