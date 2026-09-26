import unittest

from PySubtrans.Helpers.Reading import (
    READING_CHARS_PER_SECOND,
    CountReadingCharacters,
    EstimateReadingSeconds,
    GetReadingScript,
    ReadingScript,
)
from PySubtrans.Helpers.TestCases import LoggedTestCase


class TestReading(LoggedTestCase):

    reading_script_cases = [
        ("The quick brown fox", ReadingScript.ALPHABETIC),
        ("Привет, как дела?", ReadingScript.ALPHABETIC),
        ("สวัสดีครับ", ReadingScript.ALPHABETIC),
        ("你好朋友", ReadingScript.CHINESE),
        ("我用iPhone", ReadingScript.CHINESE),
        ("今日は良い天気です", ReadingScript.JAPANESE),
        ("カメラ", ReadingScript.JAPANESE),
        ("안녕하세요", ReadingScript.KOREAN),
    ]

    def test_GetReadingScript(self):
        for text, expected in self.reading_script_cases:
            with self.subTest(text=text):
                self.assertLoggedEqual("reading script", expected, GetReadingScript(text), input_value=text)

    count_cases = [
        ("Hello there!", ReadingScript.ALPHABETIC, 12),
        ("Hello  \n  there", ReadingScript.ALPHABETIC, 11),
        ("  Hello  ", ReadingScript.ALPHABETIC, 5),
        ("สวัสดี", ReadingScript.ALPHABETIC, 4),
        ("你好， 朋友。", ReadingScript.CHINESE, 6),
        ("안녕하세요 친구", ReadingScript.KOREAN, 7),
        ("👨‍👩‍👧‍👦", ReadingScript.ALPHABETIC, 1),
    ]

    def test_CountReadingCharacters(self):
        for text, script, expected in self.count_cases:
            with self.subTest(text=text):
                self.assertLoggedEqual("reading characters", expected, CountReadingCharacters(text, script), input_value=text)

    def test_EstimateReadingSeconds_at_netflix_speed(self):
        for text, script in [("Hello there!", ReadingScript.ALPHABETIC), ("你好朋友", ReadingScript.CHINESE), ("今日は", ReadingScript.JAPANESE), ("안녕하세요", ReadingScript.KOREAN)]:
            with self.subTest(text=text):
                expected = CountReadingCharacters(text, script) / READING_CHARS_PER_SECOND[script]
                self.assertLoggedEqual("reading seconds", expected, EstimateReadingSeconds(text), input_value=text)

    def test_EstimateReadingSeconds_scales_with_speed(self):
        text = "今日は良い天気です"
        baseline = EstimateReadingSeconds(text)

        self.assertLoggedEqual("half speed doubles time", 2 * baseline, EstimateReadingSeconds(text, 0.5))
        self.assertLoggedEqual("double speed halves time", baseline / 2, EstimateReadingSeconds(text, 2.0))

    def test_EstimateReadingSeconds_empty_text(self):
        self.assertLoggedEqual("no reading time", 0.0, EstimateReadingSeconds(""))


if __name__ == '__main__':
    unittest.main()
