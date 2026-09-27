"""Matching parsed translations to the original lines."""
import unittest
from datetime import timedelta

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Options import Options
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.Translation import Translation
from PySubtrans.TranslationParser import TranslationParser


def _line(number : int, text : str) -> SubtitleLine:
    return SubtitleLine.Construct(number, timedelta(seconds=number), timedelta(seconds=number + 1), text, {})


class TestSwappedTranslations(LoggedTestCase):
    def _matched_text(self, source : str, echoed_original : str, translation : str) -> str|None:
        """Parse a one-line response and return the translation matched to the source line."""
        parser = TranslationParser("Translation", Options())
        response = Translation({'text': f"#1\nOriginal>\n{echoed_original}\nTranslation>\n{translation}\n"})
        parser.ProcessTranslation(response, validate=False)

        original = _line(1, source)
        parser.MatchTranslations([original])
        return original.translation

    def test_swapped_fields_are_restored(self):
        """A response with the original and translation the wrong way round is swapped back."""
        text = self._matched_text("Hello", echoed_original="Hola", translation="Hello")

        self.assertLoggedEqual("translation", "Hola", text)

    def test_punctuation_change_is_not_a_swap(self):
        """A translation that only changes punctuation is kept, rather than replaced with the original."""
        text = self._matched_text("Okay!", echoed_original="Okay!", translation="¡Okay!")

        self.assertLoggedEqual("translation", "¡Okay!", text)


if __name__ == '__main__':
    unittest.main()
