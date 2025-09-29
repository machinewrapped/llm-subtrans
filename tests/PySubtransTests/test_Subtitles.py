import unittest
import regex
from datetime import timedelta

from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.Helpers.Text import split_sequences, standard_filler_words
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import log_info, log_input_expected_result
from PySubtrans.Helpers.SubtitleHelpers import MergeSubtitles, MergeTranslations, FindSplitPoint, GetProportionalDuration
from PySubtrans.SubtitleProcessor import SubtitleProcessor


class TestSubtitles(LoggedTestCase):

    example_line_1 = SubtitleLine("1\n00:00:01,000 --> 00:00:02,000\nThis is line 1")
    example_line_2 = SubtitleLine("2\n00:00:02,500 --> 00:00:03,500\nThis is line 2")
    example_line_3 = SubtitleLine("3\n00:00:04,000 --> 00:00:06,200\nThis is line 3")
    example_line_4 = SubtitleLine("4\n00:00:06,500 --> 00:00:07,500\nThis is line 4")
    example_line_5 = SubtitleLine("5\n00:00:08,000 --> 00:00:09,500\nThis is line 5.\nThis is line 5 continued")
    example_line_11 = SubtitleLine("11\n00:00:10,000 --> 00:00:11,000\nThis is line 11, which is a bit longer!")
    alternative_line_1 = SubtitleLine("1\n00:00:01,000 --> 00:00:02,000\nThis is an alternative line 1")
    alternative_line_2 = SubtitleLine("2\n00:00:02,500 --> 00:00:03,500\nThis is an alternative line 2")

    merge_subtitles_cases = [
        (
            [ example_line_1, example_line_2 ],
            SubtitleLine("1\n00:00:01,000 --> 00:00:03,500\nThis is line 1\nThis is line 2")
        ),
        (
            [ example_line_1, example_line_2, example_line_3 ],
            SubtitleLine("1\n00:00:01,000 --> 00:00:06,200\nThis is line 1\nThis is line 2\nThis is line 3")
        ),
        (
            [ example_line_11 ],
            SubtitleLine("11\n00:00:10,000 --> 00:00:11,000\nThis is line 11, which is a bit longer!")
        ),
        (
            [ example_line_4, example_line_5 ],
            SubtitleLine("4\n00:00:06,500 --> 00:00:09,500\nThis is line 4\nThis is line 5.\nThis is line 5 continued")
        )
    ]

    def test_MergeSubtitles(self):
        for source, expected in self.merge_subtitles_cases:
            with self.subTest(source=source):
                lines = [SubtitleLine(line) for line in source]
                expected_line = SubtitleLine(expected)
                result = MergeSubtitles(lines)
                log_input_expected_result(lines, expected_line, result)
                self.assertEqual(result, expected_line)

    merge_translation_cases = [
        (
            [ example_line_1, example_line_2 ],
            [ example_line_3, example_line_4 ],
            [ example_line_1, example_line_2, example_line_3, example_line_4 ]
        ),
        (
            [ example_line_1, example_line_2 ],
            [ example_line_1, example_line_3 ],
            [ example_line_1, example_line_2, example_line_3 ]
        ),
        (
            [ example_line_1, example_line_2 ],
            [ alternative_line_1, example_line_3 ],
            [ alternative_line_1, example_line_2, example_line_3 ]
        ),
        (
            [ example_line_1, example_line_2 ],
            [ alternative_line_1, alternative_line_2 ],
            [ alternative_line_1, alternative_line_2 ]
        )
    ]

    def test_MergeTranslations(self):
        for group_1, group_2, expected in self.merge_translation_cases:
            with self.subTest(group_1=group_1, group_2=group_2):
                merged_lines = MergeTranslations(group_1, group_2)
                log_input_expected_result(f"Merged {len(group_1)} lines and {len(group_2)} lines",
                                          expected,
                                          merged_lines)

                self.assertSequenceEqual(merged_lines, expected)

    split_point_cases = [
        ("1\n00:00:01,000 --> 00:00:05,000\nThis is a test subtitle, break after comma.", "This is a test subtitle,"),
        ("2\n00:00:06,000 --> 00:00:10,000\nSecond test subtitle. Break after period.", "Second test subtitle."),
        ("3\n00:00:11,000 --> 00:00:15,000\nThird test subtitle! Break after exclamation mark.", "Third test subtitle!"),
        ("4\n00:00:16,000 --> 00:00:20,000\nFourth test subtitle? Break after question mark.", "Fourth test subtitle?"),
        ("5\n00:00:21,000 --> 00:00:25,000\nFifth test subtitle... Break after ellipsis.", "Fifth test subtitle..."),
        ("6\n00:00:26,000 --> 00:00:30,000\nSixth test subtitle.\nBreak after newline.", "Sixth test subtitle."),
        ("7\n00:00:31,000 --> 00:00:35,000\nSeventh test subtitle.\nBreak after newline, not after the comma even if it is closer to the middle of the line.", "Seventh test subtitle."),
        ("8\n00:00:36,000 --> 00:00:40,000\nEighth test subtitle, break after second comma, because it is closer to the middle.", "Eighth test subtitle, break after second comma,"),
        ("9\n00:00:36,000 --> 00:00:40,000\nNinth test subtitle. Break after the period, not the comma even if it is closer to the middle.", "Ninth test subtitle."),
        ("10\n00:00:41,000 --> 00:00:45,000\nTenth test subtitle, <i>We should not split here, even though there is a comma in the italic block.</i>", "Tenth test subtitle,"),
        ("11\n00:00:46,000 --> 00:00:50,000\nEleventh test subtitle！Break after full-width exclamation mark.", "Eleventh test subtitle！"),
        ("12\n00:00:51,000 --> 00:00:55,000\nTwelfth test subtitle.    Break after three spaces.", "Twelfth test subtitle."),
        ("13\n00:00:56,000 --> 00:01:00,000\n\"Is this the 13th subtitle?\" Break after the quote.", "\"Is this the 13th subtitle?\""),
        ("15\n00:01:06,000 --> 00:01:10,000\nThey say, \"We should not! Split a quotation!\"", "They say,"),
        ("16\n00:01:11,000 --> 00:01:15,000\nWe can split <i>a block in tags, if they do not match</b>", "We can split <i>a block in tags,"),
        ("17\n00:01:16,000 --> 00:01:20,000\nWe shouldn't split the number 500,000 even if there is a comma in the middle.", "We shouldn't split the number 500,000 even if there is a comma in the middle."),
    ]

    def test_FindSplitPoint(self):
        split_patterns = [regex.compile(sequence) for sequence in split_sequences]

        min_duration = timedelta(seconds=1)
        min_split_chars = 3

        for source, first_part in self.split_point_cases:
            with self.subTest(source=source):
                line = SubtitleLine(source)
                if not line or not line.text:
                    self.fail("Could not parse subtitle line")

                break_point = FindSplitPoint(line, split_patterns, min_duration, min_split_chars)
                result = line.text[:break_point].strip()
                log_input_expected_result(line, first_part, result)
                self.assertEqual(result, first_part)

    proportional_duration_cases = [
        (example_line_1, 6, timedelta(seconds=0.5), timedelta(seconds=0.5)),
        (example_line_2, 4, timedelta(seconds=0.8), timedelta(seconds=0.8)),
        (example_line_3, 10, timedelta(seconds=0.75), timedelta(seconds=1.0, microseconds=571429)),
        (example_line_3, 14, timedelta(seconds=0.75), timedelta(seconds=2.0, microseconds=200000)),
        (example_line_5, 8, timedelta(seconds=0.6), timedelta(seconds=0.6)),
        (example_line_5, 25, timedelta(seconds=0.6), timedelta(microseconds=937500))
    ]

    def test_GetProportionalDuration(self):
        for line, characters, min_duration, expected_duration in self.proportional_duration_cases:
            with self.subTest(line=line, characters=characters):
                result = GetProportionalDuration(line, characters, min_duration=min_duration)
                log_input_expected_result((line.text, characters, min_duration.total_seconds()), expected_duration, result)
                self.assertEqual(result, expected_duration)

class SubtitleProcessorTests(LoggedTestCase):
    example_line_1 = "1\n00:00:01,000 --> 00:00:02,000\nThis is line 1"
    example_line_2 = "2\n00:00:02,500 --> 00:00:03,500\nThis is line 2"
    example_line_3 = "3\n00:00:31,000 --> 00:00:35,000\nThird test subtitle.\nBreak after newline, not after the comma even though it is central."
    example_line_4 = "4\n00:00:36,000 --> 00:00:40,000\nFourth test subtitle, break after second comma, because it is closer to the middle."
    example_line_5 = "5\n00:00:42,000 --> 00:00:46,000\nFifth test subtitle. Break after the period, not the comma even if it is closer to the middle."
    example_line_6 = "6\n00:00:42,000 --> 00:00:50,000\nSixth test subtitle, Break after the period, and again after the comma."
    example_line_7 = "7\n00:00:50,000 --> 00:00:55,000\nSeventh test subtitle, <i>We should not split here, even though there is a comma in the italic block.</i>"
    example_line_8 = "8\n00:00:55,000 --> 00:01:00,000\nBreak this! But not at the exclamation mark because it would be too unbalanced."
    example_line_9 = "9\n00:01:00,000 --> 00:01:05,000\nUmm, this subtitle has some, err, filler words that should be removed."
    example_line_10 = "227\n00:22:53,260 --> 00:23:01,472\n不过，满清对浙江很注意，派过去的都是他们的能源，你处处有性命之忧,"
    example_line_11 = "345\n00:49:03,294 --> 00:49:06,005\nNo escape\u2014I have one condition"

    preprocess_cases = [
        ([example_line_1, example_line_2], {}, [example_line_1, example_line_2]),  # No changes
        ([example_line_3, example_line_4], { "max_line_duration": 3.5, "min_line_duration": 1.0 },
            [
                "3\n00:00:31,000 --> 00:00:31,904\nThird test subtitle.",
                "4\n00:00:31,954 --> 00:00:35,000\nBreak after newline, not after the comma even though it is central.",
                "5\n00:00:36,000 --> 00:00:38,263\nFourth test subtitle, break after second comma,",
                "6\n00:00:38,313 --> 00:00:40,000\nbecause it is closer to the middle.",
            ]),
        ([example_line_5], { "max_line_duration": 3.5, "min_line_duration": 1.0 },
            [
                "5\n00:00:42,000 --> 00:00:42,843\nFifth test subtitle.",
                "6\n00:00:42,893 --> 00:00:46,000\nBreak after the period, not the comma even if it is closer to the middle."
            ]),
        ([example_line_6], { "max_line_duration": 3, "min_line_duration": 1.0 },
            [
                "6\n00:00:42,000 --> 00:00:44,346\nSixth test subtitle,",
                "7\n00:00:44,396 --> 00:00:47,020\nBreak after the period,",
                "8\n00:00:47,070 --> 00:00:50,000\nand again after the comma."
            ]),
        ([example_line_7], { "max_line_duration": 3.5, "min_line_duration": 1.0 },
            [
                "7\n00:00:50,000 --> 00:00:51,045\nSeventh test subtitle,",
                "8\n00:00:51,095 --> 00:00:55,000\n<i>We should not split here, even though there is a comma in the italic block.</i>"
            ]),
        ([example_line_9], { "remove_filler_words": True, 'filler_words': standard_filler_words},
            [
                "9\n00:01:00,000 --> 00:01:05,000\nThis subtitle has some filler words that should be removed."
            ]),
        ([example_line_10],
         { "max_line_duration": 3.5, "min_line_duration": 1.0, },
            [
            "227\n00:22:53,260 --> 00:22:56,196\n不过，满清对浙江很注意，",
            "228\n00:22:56,246 --> 00:22:59,182\n派过去的都是他们的能源，",
            "229\n00:22:59,232 --> 00:23:01,472\n你处处有性命之忧,"
            ]),
        ([example_line_11], { "convert_wide_dashes": True }, [ "345\n00:49:03,294 --> 00:49:06,005\nNo escape - I have one condition" ])
    ]

    def test_Preprocess(self):
        for source, settings, expected in self.preprocess_cases:
            with self.subTest(source=source, settings=settings):
                processor = SubtitleProcessor(settings)
                input = [SubtitleLine(line) for line in source]

                result = processor.PreprocessSubtitles(input)
                result_lines = [f"{line.number}\n{line.srt_start} --> {line.srt_end}\n{line.text}" for line in result]

                self._log_expected_vs_actual(result_lines, expected)
                self.assertSequenceEqual(result_lines, expected)

    postprocess_cases = [
        ([example_line_1, example_line_2], { "break_long_lines": True}, [example_line_1, example_line_2]),  # No changes
        ([example_line_3, example_line_4], { 'break_long_lines': False}, [example_line_3, example_line_4]),  # No changes
        ([example_line_3, example_line_4],
            { 'break_long_lines': True, 'max_single_line_length': 30, 'min_single_line_length': 10 },
            [
                "3\n00:00:31,000 --> 00:00:35,000\nThird test subtitle.\nBreak after newline, not after the comma even though it is central.",
                "4\n00:00:36,000 --> 00:00:40,000\nFourth test subtitle, break after second comma,\nbecause it is closer to the middle."
            ]),
        ([example_line_5],
            { 'break_long_lines': True, 'max_single_line_length': 80, 'min_single_line_length': 10 },
            [
                "5\n00:00:42,000 --> 00:00:46,000\nFifth test subtitle.\nBreak after the period, not the comma even if it is closer to the middle."
            ]),
         ([example_line_7],
            { 'break_long_lines': True, 'max_single_line_length': 30, 'min_single_line_length': 10 },
            [
                "7\n00:00:50,000 --> 00:00:55,000\nSeventh test subtitle,\n<i>We should not split here, even though there is a comma in the italic block.</i>"
            ]),
        ([example_line_8],
            { 'break_long_lines': True, 'max_single_line_length': 44, 'min_single_line_length': 6 },
            [
                "8\n00:00:55,000 --> 00:01:00,000\nBreak this! But not at the exclamation\nmark because it would be too unbalanced."
            ]),
        ([example_line_9],
            { 'remove_filler_words': True, 'filler_words': standard_filler_words, 'break_long_lines': True, 'max_single_line_length': 30, 'min_single_line_length': 10},
            [
                "9\n00:01:00,000 --> 00:01:05,000\nThis subtitle has some filler\nwords that should be removed."
            ]),
        (["227\n00:22:53,260 --> 00:22:56,196\n"], { }, [ "227\n00:22:53,260 --> 00:22:56,196\n"]),
        ([example_line_11], { "convert_wide_dashes": True }, [ "345\n00:49:03,294 --> 00:49:06,005\nNo escape - I have one condition"])
    ]

    def test_Postprocess(self):
        for source, settings, expected in self.postprocess_cases:
            with self.subTest(source=source, settings=settings):
                processor = SubtitleProcessor(settings)
                input = [SubtitleLine(line) for line in source]

                result = processor.PostprocessSubtitles(input)
                result_lines = [f"{line.number}\n{line.srt_start} --> {line.srt_end}\n{line.text}" for line in result]

                self._log_expected_vs_actual(result_lines, expected)
                self.assertSequenceEqual(result_lines, expected)

    def _log_expected_vs_actual(self, result : list[str], expected_result : list[str]):
        log_info(',\n'.join(self._format_lines(expected_result)), prefix="===".ljust(10))
        log_info(',\n'.join(self._format_lines(result)), prefix="-->".ljust(10))

    def _format_lines(self, expected_result):
        return [f"\"{line}\"".replace('\n', '\\n') for line in expected_result]

if __name__ == '__main__':
    unittest.main()
