import unittest

from PySubtrans.Helpers import GetOutputPath
from PySubtrans.Helpers.TestCases import LoggedTestCase


class TestGetOutputPath(LoggedTestCase):
    """Language suffix sanitisation in GetOutputPath."""

    def test_plain_language(self):
        """Simple language name is lowercased."""
        result = GetOutputPath("movie.mkv", "Chinese", ".srt")

        self.assertLoggedEqual("plain language", "movie.chinese.srt", self._basename(result))

    def test_language_with_spaces(self):
        """Spaces in language names become hyphens."""
        result = GetOutputPath("movie.mkv", "Brazilian Portuguese", ".srt")

        self.assertLoggedEqual("spaced language", "movie.brazilian-portuguese.srt", self._basename(result))

    def test_language_with_slashes(self):
        """Path separators are stripped so the suffix stays in one path component."""
        result = GetOutputPath("movie.mkv", "zh/cn", ".srt")

        self.assertLoggedEqual("slash stripped", "movie.zhcn.srt", self._basename(result))

    def test_language_with_backslash(self):
        """Backslash path separators are stripped."""
        result = GetOutputPath("movie.mkv", "zh\\cn", ".srt")

        self.assertLoggedEqual("backslash stripped", "movie.zhcn.srt", self._basename(result))

    def test_empty_language_after_sanitisation(self):
        """A language that reduces to only separators is treated as no language."""
        result = GetOutputPath("movie.mkv", "//", ".srt")

        self.assertLoggedEqual("empty sanitised", "movie.srt", self._basename(result))

    def test_none_language(self):
        """None language produces no suffix."""
        result = GetOutputPath("movie.mkv", None, ".srt")

        self.assertLoggedEqual("no language", "movie.srt", self._basename(result))

    def test_duplicate_suffix_not_repeated(self):
        """An existing language suffix is not doubled."""
        result = GetOutputPath("movie.chinese.mkv", "Chinese", ".srt")

        self.assertLoggedEqual("no duplication", "movie.chinese.srt", self._basename(result))

    @staticmethod
    def _basename(path : str|None) -> str:
        """Extract just the filename for portable assertions."""
        import os
        return os.path.basename(path) if path else ""


if __name__ == '__main__':
    unittest.main()
