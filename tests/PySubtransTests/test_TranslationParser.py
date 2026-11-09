"""Matching parsed translations to the original lines."""
import unittest
from datetime import timedelta

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Options import Options
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.Translation import Translation
from PySubtrans.TranslationParser import TranslationParser
from PySubtrans.ValidationError import RepeatedResponseLabelError


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


class TestRepeatedResponseLabels(LoggedTestCase):
    def test_repeated_translation_label_requires_retry(self) -> None:
        """A trailing label invalidates its cue with or without text after it."""
        for suffix in ("", "\nHello.", "\nDifferent text."):
            with self.subTest(suffix=suffix):
                parser = TranslationParser("Translation", Options())
                response = Translation({'text': f"#21\nTranslation>\nHello.\nTranslation>{suffix}"})
                parser.ProcessTranslation(response)

                self.assertLoggedEqual("affected cue numbers", [[21]], [
                    error.line_numbers for error in parser.errors if isinstance(error, RepeatedResponseLabelError)
                ])

    def test_repeated_custom_label_in_fallback_requires_retry(self) -> None:
        """Colon-delimited responses keep adjacent cues and validate the active task label."""
        parser = TranslationParser("Rewrite", Options())
        response = Translation({'text': "#21\r\nRewrite:\r\nHello.\r\n  Rewrite: \r\nHello.\n\n#22\nRewrite:\nNext."})
        parser.ProcessTranslation(response)

        self.assertLoggedEqual("parsed cue numbers", [21, 22], [line.number for line in parser.translated])
        self.assertLoggedEqual("adjacent cue text", "Next.", parser.translations[22].text)
        self.assertLoggedEqual("affected cue numbers", [[21]], [
            error.line_numbers for error in parser.errors if isinstance(error, RepeatedResponseLabelError)
        ])

    def test_inline_label_text_is_preserved(self) -> None:
        """A label mentioned within dialogue remains ordinary subtitle text."""
        parser = TranslationParser("Translation", Options())
        body = "Type Translation> here."
        parser.ProcessTranslation(Translation({'text': f"#21\nTranslation>\n{body}"}))

        self.assertLoggedEqual("translation text", body, parser.translations[21].text)
        self.assertLoggedEqual("validation errors", [], parser.errors)

    def test_label_free_fallback_is_preserved(self) -> None:
        """Numbered responses without labels still use the final fallback."""
        parser = TranslationParser("Translation", Options())
        parser.ProcessTranslation(Translation({'text': "#21\nHello.\n\n#22\nNext."}))

        self.assertLoggedEqual("parsed cues", [(21, "Hello."), (22, "Next.")], [
            (line.number, line.text) for line in parser.translated
        ])
        self.assertLoggedEqual("validation errors", [], parser.errors)


if __name__ == '__main__':
    unittest.main()
