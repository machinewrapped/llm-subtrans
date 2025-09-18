import unittest
from enum import Enum

from PySubtrans.Helpers import GetValueName, GetValueFromName
from PySubtrans.Helpers.Parse import ParseDelayFromHeader, ParseNames
from PySubtrans.Helpers.Tests import log_input_expected_result, log_test_name

class TestParseDelayFromHeader(unittest.TestCase):
    test_cases = [
        ("5", 5.0),
        ("10s", 10.0),
        ("5m", 300.0),
        ("500ms", 1.0),
        ("1500ms", 1.5),
        ("abc", 32.1),
    ]

    def test_ParseDelayFromHeader(self):
        log_test_name("ParseDelayFromHeader")
        for value, expected in self.test_cases:
            with self.subTest(value=value):
                result = ParseDelayFromHeader(value)
                log_input_expected_result(value, expected, result)
                self.assertEqual(result, expected)


class TestParseNames(unittest.TestCase):
    test_cases = [
        ("John, Jane, Alice", ["John", "Jane", "Alice"]),
        (["John", "Jane", "Alice"], ["John", "Jane", "Alice"]),
        ("Mike, Murray, Mabel, Marge", ["Mike", "Murray", "Mabel", "Marge"]),
        ("", []),
        ([] , []),
        ([""], [])
    ]

    def test_ParseNames(self):
        log_test_name("ParseNames")
        for value, expected in self.test_cases:
            with self.subTest(value=value):
                result = ParseNames(value)
                log_input_expected_result(value, expected, result)
                self.assertSequenceEqual(result, expected)

class TestParseValues(unittest.TestCase):
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
        log_test_name("GetValueName")
        for value, expected in self.get_value_name_cases:
            with self.subTest(value=value):
                result = GetValueName(value)
                log_input_expected_result(value, expected, result)
                self.assertEqual(result, expected)

    get_value_from_name_cases = [
        ("Test Name", ["Test Name", "Another Name", "Yet Another Name"], None, "Test Name"),
        ("Nonexistent Name", ["Test Name", "Another Name", "Yet Another Name"], "Default Value", "Default Value"),
        (34567, [12345, 34567, 98765], None, 34567),
        ("12345", [12345, 34567, 98765], None, 12345),
        ("Test2", TestEnum, None, TestEnum.Test2)
    ]

    def test_GetValueFromName(self):
        log_test_name("GetValueFromName")
        for value, names, default, expected in self.get_value_from_name_cases:
            with self.subTest(value=value):
                result = GetValueFromName(value, names, default)
                log_input_expected_result((value, names, default), expected, result)
                self.assertEqual(result, expected)

if __name__ == '__main__':
    unittest.main()