import os
import tempfile
import unittest
from datetime import timedelta

from PySubtrans.Formats.SrtFileHandler import SrtFileHandler
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleBuilder import SubtitleBuilder
from PySubtrans.SubtitleEditor import SubtitleEditor
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.Subtitles import NETFLIX_FRAME_RATE, NETFLIX_MIN_GAP_FRAMES, SaveSettings, Subtitles


class NetflixTimingTests(LoggedTestCase):
    """Tests for extending short subtitles on save with Netflix's timing guide."""

    def test_NetflixTiming_uses_target_language_reading_speed(self):
        # 40 characters, read at 20 per second in English and 17 in French
        text = "The quick brown fox jumps over lazy dogs"
        save_settings = SaveSettings(SettingsType({
            'min_line_duration': 0.8,
        }))

        for target_language, expected_seconds in [("English", 2.0), ("French (Canada)", 40 / 17)]:
            with self.subTest(target_language=target_language):
                line = SubtitleLine(f"1\n00:00:01,000 --> 00:00:01,100\n{text}")
                subtitles = Subtitles(settings=SettingsType({ 'target_language': target_language }))

                result = subtitles._apply_netflix_timing([line], save_settings)

                expected_end = timedelta(seconds=1) + timedelta(seconds=expected_seconds)
                self.assertLoggedEqual("reading time for target language", expected_end, result[0].end, input_value=target_language)
                self.assertLoggedEqual("source remains unchanged", timedelta(seconds=1.1), line.end)

    def test_NetflixTiming_detects_language_without_target_language(self):
        source = [
            SubtitleLine("1\n00:00:01,000 --> 00:00:01,200\nabcdefgh"),
            SubtitleLine("2\n00:00:10,000 --> 00:00:10,200\n你好朋友我们走吧"),
            SubtitleLine("3\n00:00:20,000 --> 00:00:20,200\n今日は良い天気です"),
            SubtitleLine("4\n00:00:30,000 --> 00:00:30,200\n안녕하세요 친구들 반가워요"),
        ]
        save_settings = SaveSettings(SettingsType({
            'min_line_duration': 0.8,
        }))

        result = Subtitles()._apply_netflix_timing(source, save_settings)

        durations = [line.end - line.start for line in result]
        self.assertLoggedEqual("latin text uses minimum duration", timedelta(seconds=0.8), durations[0])
        self.assertLoggedEqual("chinese at 9 per second", timedelta(seconds=8 / 9), durations[1])
        self.assertLoggedEqual("kanji with kana at 4 per second", timedelta(seconds=9 / 4), durations[2])
        self.assertLoggedEqual("korean spaces count half at 12 per second", timedelta(seconds=13 / 12), durations[3])

    def test_NetflixTiming_ignores_formatting(self):
        line = SubtitleLine("1\n00:00:01,000 --> 00:00:01,100\n<i>Hello</i> {\\an8}there")
        subtitles = Subtitles(settings=SettingsType({ 'target_language': 'English' }))
        save_settings = SaveSettings(SettingsType({
            'min_line_duration': 0.0,
        }))

        result = subtitles._apply_netflix_timing([line], save_settings)

        self.assertLoggedEqual("11 visible characters at 20 per second", timedelta(seconds=1.55), result[0].end)

    def test_NetflixTiming_caps_at_maximum_duration(self):
        long_text = "今日は良い天気です" * 4
        source = [
            SubtitleLine(f"1\n00:00:01,000 --> 00:00:01,200\n{long_text}"),
            SubtitleLine(f"2\n00:00:20,000 --> 00:00:29,000\n{long_text}"),
        ]
        save_settings = SaveSettings(SettingsType({
            'min_line_duration': 0.8,
        }))

        result = Subtitles()._apply_netflix_timing(source, save_settings)

        self.assertLoggedEqual("extension capped at 7 seconds", timedelta(seconds=8), result[0].end)
        self.assertLoggedEqual("longer line not shortened", timedelta(seconds=29), result[1].end)

    def test_NetflixTiming_does_not_close_gaps_past_maximum_duration(self):
        source = [
            SubtitleLine("1\n00:00:01,000 --> 00:00:07,900\nA long subtitle"),
            SubtitleLine("2\n00:00:08,200 --> 00:00:09,000\nNext subtitle"),
        ]
        save_settings = SaveSettings(SettingsType({
            'min_line_duration': 0.8,
        }))

        result = Subtitles()._apply_netflix_timing(source, save_settings)

        self.assertLoggedEqual("gap left open", timedelta(seconds=7.9), result[0].end)

    def test_NetflixTiming_adjustment_scales_reading_speed(self):
        # 40 characters at 20 per second in English
        text = "The quick brown fox jumps over lazy dogs"
        subtitles = Subtitles(settings=SettingsType({ 'target_language': 'English' }))

        for adjustment, expected_seconds in [(100, 2.0), (50, 4.0), (200, 1.0)]:
            with self.subTest(adjustment=adjustment):
                line = SubtitleLine(f"1\n00:00:01,000 --> 00:00:01,100\n{text}")
                save_settings = SaveSettings(SettingsType({
                    'min_line_duration': 0.0,
                    'netflix_timings_adjustment': adjustment,
                }))

                result = subtitles._apply_netflix_timing([line], save_settings)

                expected_end = timedelta(seconds=1) + timedelta(seconds=expected_seconds)
                self.assertLoggedEqual("scaled reading time", expected_end, result[0].end, input_value=adjustment)

    def test_NetflixTiming_zero_adjustment_applies_minimum_only(self):
        line = SubtitleLine("1\n00:00:01,000 --> 00:00:01,100\nThe quick brown fox jumps over the lazy dog")
        save_settings = SaveSettings(SettingsType({
            'min_line_duration': 0.8,
            'netflix_timings_adjustment': 0,
        }))

        result = Subtitles()._apply_netflix_timing([line], save_settings)

        self.assertLoggedEqual("minimum duration only", timedelta(seconds=1.8), result[0].end)

    def test_NetflixTiming_closes_gaps_of_3_to_11_frames(self):
        min_gap = timedelta(seconds=NETFLIX_MIN_GAP_FRAMES / NETFLIX_FRAME_RATE)
        gap_cases = [
            ("00:00:02,100", False),
            ("00:00:02,125", True),
            ("00:00:02,300", True),
            ("00:00:02,458", True),
            ("00:00:02,500", False),
        ]
        save_settings = SaveSettings(SettingsType({
            'min_line_duration': 0.0,
        }))

        for next_start, closed in gap_cases:
            with self.subTest(next_start=next_start):
                source = [
                    SubtitleLine("1\n00:00:01,000 --> 00:00:02,000\nHi"),
                    SubtitleLine(f"2\n{next_start} --> 00:00:03,000\nThere"),
                ]

                result = Subtitles()._apply_netflix_timing(source, save_settings)

                expected_end = source[1].start - min_gap if closed else timedelta(seconds=2)
                self.assertLoggedEqual("end after gap rule", expected_end, result[0].end, input_value=next_start)

    def test_NetflixTiming_caps_extension_before_next_subtitle(self):
        source = [
            SubtitleLine("1\n00:00:01,000 --> 00:00:01,200\n今日は良い天気です"),
            SubtitleLine("2\n00:00:02,000 --> 00:00:03,000\nNext subtitle"),
        ]
        save_settings = SaveSettings(SettingsType({
            'min_line_duration': 0.8,
        }))

        result = Subtitles()._apply_netflix_timing(source, save_settings)

        expected_end = timedelta(seconds=2) - timedelta(seconds=NETFLIX_MIN_GAP_FRAMES / NETFLIX_FRAME_RATE)
        self.assertLoggedEqual("capped 2 frames before next subtitle", expected_end, result[0].end)

    def test_NetflixTiming_preserves_existing_overlap(self):
        source = [
            SubtitleLine("1\n00:00:01,000 --> 00:00:03,000\nA long translated subtitle"),
            SubtitleLine("2\n00:00:02,500 --> 00:00:04,000\nNext subtitle"),
        ]
        save_settings = SaveSettings(SettingsType({
            'min_line_duration': 0.8,
        }))

        result = Subtitles()._apply_netflix_timing(source, save_settings)

        self.assertLoggedEqual("existing overlap remains unchanged", timedelta(seconds=3), result[0].end)

    def test_NetflixTiming_ignores_frame_sized_extensions(self):
        line = SubtitleLine("1\n00:00:01,000 --> 00:00:01,780\nHi")
        save_settings = SaveSettings(SettingsType({
            'min_line_duration': 0.8,
        }))

        result = Subtitles()._apply_netflix_timing([line], save_settings)

        self.assertLoggedEqual("20ms extension ignored", timedelta(seconds=1.78), result[0].end)

    def test_SaveTranslation_uses_netflix_timing_guide(self):
        subtitles = (SubtitleBuilder(max_batch_size=1)
            .AddLines([
                (timedelta(seconds=1), timedelta(seconds=1.1), "今日は良い天気です"),
            ])
            .Build())
        save_settings = SaveSettings(SettingsType({
            'extend_short_subtitles': True,
            'use_netflix_timing_guide': True,
            'min_line_duration': 0.8,
            'seconds_per_character': 10.0,
        }))

        with SubtitleEditor(subtitles) as editor:
            editor.DuplicateOriginalsAsTranslations()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".srt") as output_file:
            output_path = output_file.name
        self.addCleanup(os.remove, output_path)

        subtitles.SaveTranslation(output_path, save_settings=save_settings)
        output_data = SrtFileHandler().load_file(output_path)

        # 9 characters at 4 per second, ignoring seconds_per_character
        self.assertLoggedEqual("netflix reading time", timedelta(seconds=3.25), output_data.lines[0].end)
        self.assertLoggedEqual(
            "stored translation unchanged",
            timedelta(seconds=1.1),
            subtitles.scenes[0].batches[0].translated[0].end,
        )


if __name__ == '__main__':
    unittest.main()
