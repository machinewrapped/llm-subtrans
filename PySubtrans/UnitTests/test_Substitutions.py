import unittest
from PySubtrans.Substitutions import Substitutions
from PySubtrans.Helpers.Tests import log_test_name, log_input_expected_result

class TestSubstitutions(unittest.TestCase):
    parse_cases = [
        ([], {}),
        ("", {}),
        ({"before": "after", "hello": "world"}, {"before": "after", "hello": "world"}),
        ("before::after\nhello::world", {"before": "after", "hello": "world"}),
        (["before::after", "hello::world"], {"before": "after", "hello": "world"}),
    ]

    def test_ParseSubstitutions(self):
        log_test_name("ParseSubstitutions")
        for value, expected in self.parse_cases:
            with self.subTest(value=value):
                result = Substitutions.Parse(value)
                log_input_expected_result(value, expected, result)
                self.assertEqual(result, expected)

    perform_cases = [
        (["before::after", "hello::world"], "before hello", "after world", Substitutions.Mode.WholeWords),
        ({"before": "after", "hello": "world"}, "This is the string before", "This is the string after", Substitutions.Mode.WholeWords),
        ({"bef": "aft", "hello": "world"}, "before hello", "before world", Substitutions.Mode.WholeWords),
        ({"Shaw Brothers": "Snowboarders"}, "Shaw Brothers is a film company", "Snowboarders is a film company", Substitutions.Mode.WholeWords),
        ({"Shaw Brothers": "Snow Boarders"}, "We all love Shaw Brothers films here!", "We all love Snow Boarders films here!", Substitutions.Mode.WholeWords),
        ({"李王": "Li Wang"}, "Mr. 李王 is a Chinese name", "Mr. Li Wang is a Chinese name", Substitutions.Mode.WholeWords),
        ({"東京": "Tokyo"}, "東京 is the capital of Japan", "Tokyo is the capital of Japan", Substitutions.Mode.WholeWords),
        ({"big": "small"}, "The big brown fox jumped over the big fence", "The small brown fox jumped over the small fence", Substitutions.Mode.WholeWords),
        ({"東京": "Tokyo"}, "東京都は日本の首都です", "Tokyo都は日本の首都です", Substitutions.Mode.PartialWords),
        ({"李王": "Li Wang"}, "在学术交流会上，李王详细阐述了他的观点。晚宴上，大家继续讨论李王的提议。", "在学术交流会上，Li Wang详细阐述了他的观点。晚宴上，大家继续讨论Li Wang的提议。", Substitutions.Mode.PartialWords),
    ]

    def test_PerformSubstitutions(self):
        log_test_name("PerformSubstitutions")
        for substitutions, value, expected, mode in self.perform_cases:
            with self.subTest(value=value):
                helper = Substitutions(substitutions, mode)
                result = helper.PerformSubstitutions(value)
                log_input_expected_result((value, substitutions), expected, result)
                self.assertEqual(result, expected)

    def test_PerformSubstitutionsAuto(self):
        log_test_name("PerformSubstitutions2")
        for substitutions, value, expected, _ in self.perform_cases:
            with self.subTest(value=value):
                helper = Substitutions(substitutions, Substitutions.Mode.Auto)
                result = helper.PerformSubstitutions(value)
                log_input_expected_result((value, substitutions), expected, result)
                self.assertEqual(result, expected)

if __name__ == '__main__':
    unittest.main()