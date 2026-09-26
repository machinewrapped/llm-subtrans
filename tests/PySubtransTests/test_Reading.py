import unittest

from PySubtrans.Helpers.Reading import (
    CountReadingCharacters,
    DetectReadingLanguage,
    EstimateReadingSeconds,
    GetReadingLanguage,
    GetReadingSpeed,
)
from PySubtrans.Helpers.TestCases import LoggedTestCase


class TestReading(LoggedTestCase):

    reading_language_cases = [
        ("English", 'en'),
        ("Chinese (Simplified)", 'zh'),
        ("Traditional Chinese", 'zh'),
        ("French (Canada)", 'fr'),
        ("Brazilian Portuguese", 'pt'),
        ("日本語", 'ja'),
        ("ko", 'ko'),
        ("Klingon", None),
        ("", None),
        (None, None),
    ]

    def test_GetReadingLanguage(self):
        for target_language, expected in self.reading_language_cases:
            with self.subTest(target_language=target_language):
                self.assertLoggedEqual("reading language", expected, GetReadingLanguage(target_language), input_value=target_language)

    detect_language_cases = [
        ("The quick brown fox", None),
        ("Привет, как дела?", None),
        ("สวัสดีครับ", None),
        ("你好朋友", 'zh'),
        ("我用iPhone", 'zh'),
        ("今日は良い天気です", 'ja'),
        ("カメラ", 'ja'),
        ("안녕하세요", 'ko'),
        ("नमस्ते", 'hi'),
        ("مرحبا", 'ar'),
    ]

    def test_DetectReadingLanguage(self):
        for text, expected in self.detect_language_cases:
            with self.subTest(text=text):
                self.assertLoggedEqual("detected language", expected, DetectReadingLanguage(text), input_value=text)

    reading_speed_cases = [
        ('en', 20.0),
        ('ar', 20.0),
        ('hi', 22.0),
        ('ko', 12.0),
        ('zh', 9.0),
        ('ja', 7.0),
        ('fr', 17.0),
        ('af', 20.0),
        ('zu', 20.0),
        ('de', 17.0),
        (None, 17.0),
    ]

    def test_GetReadingSpeed(self):
        for language, expected in self.reading_speed_cases:
            with self.subTest(language=language):
                self.assertLoggedEqual("reading speed", expected, GetReadingSpeed(language), input_value=language)

    count_cases = [
        ("Hello there!", 'en', 12.0),
        ("Hello  \n  there", 'en', 11.0),
        ("  Hello  ", 'en', 5.0),
        ("café", 'fr', 4.0),
        ("สวัสดี", 'th', 4.0),
        ("你好，朋友。", 'zh', 6.0),
        ("我用iPhone", 'zh', 5.0),
        ("안녕하세요 친구", 'ko', 7.5),
        ("今日は　晴れ", 'ja', 6.0),
        ("OK!", 'ja', 1.5),
    ]

    def test_CountReadingCharacters(self):
        for text, language, expected in self.count_cases:
            with self.subTest(text=text):
                self.assertLoggedEqual("reading characters", expected, CountReadingCharacters(text, language), input_value=text)

    def test_EstimateReadingSeconds_for_language(self):
        self.assertLoggedEqual("english", 0.6, EstimateReadingSeconds("Hello there!", 'en'))
        self.assertLoggedEqual("japanese", 1.0, EstimateReadingSeconds("今日は良い天気", 'ja'))

    def test_EstimateReadingSeconds_detects_language(self):
        self.assertLoggedEqual("chinese detected", 4 / 9, EstimateReadingSeconds("你好朋友"))
        self.assertLoggedEqual("default speed", 12 / 17, EstimateReadingSeconds("Hello there!"))

    def test_EstimateReadingSeconds_scales_with_speed(self):
        text = "今日は良い天気です"
        baseline = EstimateReadingSeconds(text, 'ja')

        self.assertLoggedEqual("half speed doubles time", 2 * baseline, EstimateReadingSeconds(text, 'ja', 0.5))
        self.assertLoggedEqual("double speed halves time", baseline / 2, EstimateReadingSeconds(text, 'ja', 2.0))

    def test_EstimateReadingSeconds_empty_text(self):
        self.assertLoggedEqual("no reading time", 0.0, EstimateReadingSeconds(""))


if __name__ == '__main__':
    unittest.main()
