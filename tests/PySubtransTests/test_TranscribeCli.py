"""Command-line options for scripts/transcribe.py (no media or backends needed)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'scripts')))

import transcribe  # type: ignore[import-not-found] - scripts dir added to sys.path above

from PySubtrans.Helpers.TestCases import LoggedTestCase


class TestTranscribeCliOptions(LoggedTestCase):
    def _parse(self, *argv : str):
        return transcribe.CreateTranscribeParser().parse_args(list(argv))

    def test_format_defaults_to_srt(self):
        """Transcribed output defaults to SRT."""
        args = self._parse("movie.mkv")

        self.assertLoggedEqual("default format", "srt", args.format)

    def test_format_ass_selected(self):
        """ASS output is selectable."""
        args = self._parse("movie.mkv", "--format", "ass")

        self.assertLoggedEqual("ass format", "ass", args.format)

    def test_format_vtt_selected(self):
        """VTT output is selectable."""
        args = self._parse("movie.mkv", "--format", "vtt")

        self.assertLoggedEqual("vtt format", "vtt", args.format)

    def test_chunk_bounds_default_to_provider(self):
        """Chunk bounds stay unset so provider recommendations apply."""
        args = self._parse("movie.mkv")

        self.assertLoggedEqual("min unset", None, args.min_chunk)
        self.assertLoggedEqual("max unset", None, args.max_chunk)


if __name__ == '__main__':
    unittest.main()
