"""Speaker labels in translation prompts and response parsing."""
import os
import tempfile
import unittest
from datetime import timedelta

from PySubtrans.Helpers.InstructionsHelpers import LoadInstructionsFile, SaveInstructions
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Instructions import Instructions, default_speaker_instructions
from PySubtrans.Options import Options
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.SubtitleTranslator import LinesHaveSpeakers
from PySubtrans.TranslationParser import TranslationParser, _strip_speaker_prefix
from PySubtrans.TranslationPrompt import TranslationPrompt, _get_line_prompt, default_line_template


def _line(number : int, text : str, speaker : str|None = None) -> SubtitleLine:
    metadata = {'speaker': speaker} if speaker else {}
    return SubtitleLine.Construct(number, timedelta(seconds=number),
                                  timedelta(seconds=number + 1), text, metadata)


class TestSpeakerPrompt(LoggedTestCase):
    def test_speaker_field_emitted(self):
        """Lines with speaker metadata gain a Speaker> field."""
        prompt = _get_line_prompt(_line(200, "hello", "Amina"), default_line_template)

        self.assertLoggedIn("speaker field", "Speaker> Amina", prompt or "")
        self.assertLoggedIn("number first", "#200\nSpeaker> Amina\nOriginal>", prompt or "")

    def test_no_speaker_no_field(self):
        """Lines without speakers render exactly as before."""
        prompt = _get_line_prompt(_line(200, "hello"), default_line_template)

        self.assertLoggedEqual("unchanged template", "#200\nOriginal>\nhello\nTranslation>\n", prompt)

    def test_custom_template_ignores_speaker(self):
        """Custom templates without the placeholder keep working."""
        prompt = _get_line_prompt(_line(200, "hello", "Amina"), "#{number}: {text}")

        self.assertLoggedEqual("custom format", "#200: hello", prompt)

    def test_batch_prompt_marks_speakers(self):
        """Batch prompts carry speaker context per line."""
        prompt = TranslationPrompt("Translate", True)
        batch = prompt.GenerateBatchPrompt([_line(200, "hello", "Amina"), _line(201, "hi")])

        self.assertLoggedEqual("one speaker field", 1, batch.count("Speaker>"))
        self.assertLoggedIn("speaker named", "Speaker> Amina", batch)

    def test_instructions_mention_speaker(self):
        """Speaker guidance lives in its own overridable field."""
        instructions = Instructions({})

        self.assertLoggedEqual("default field", default_speaker_instructions, instructions.speaker_instructions)
        self.assertLoggedIn("guidance", "Speaker>", instructions.speaker_instructions or "")
        self.assertLoggedIn("settings key", "speaker_instructions", instructions.GetSettings())


class TestSpeakerInstructionsFile(LoggedTestCase):
    def _write_file(self, directory : str, body : str) -> str:
        path = os.path.join(directory, "instructions.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        return path

    def test_section_overrides_default(self):
        """Instruction files can override the speaker guidance."""
        body = ("### prompt\nTranslate\n\n### instructions\nDo it\n\n"
                "### speaker_instructions\nCustom speaker rules\n")

        with tempfile.TemporaryDirectory() as directory:
            instructions = LoadInstructionsFile(self._write_file(directory, body))

        self.assertLoggedEqual("custom field", "Custom speaker rules", instructions.speaker_instructions)

    def test_missing_section_inherits_default(self):
        """Files without the section inherit the default guidance."""
        body = "### prompt\nTranslate\n\n### instructions\nDo it\n"

        with tempfile.TemporaryDirectory() as directory:
            instructions = LoadInstructionsFile(self._write_file(directory, body))

        self.assertLoggedEqual("default field", default_speaker_instructions, instructions.speaker_instructions)

    def test_save_writes_section(self):
        """Saved instruction files round-trip the speaker section."""
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "out.txt")
            SaveInstructions(Instructions({}), path)

            with open(path, encoding="utf-8") as f:
                content = f.read()

        self.assertLoggedIn("section header", "### speaker_instructions", content)
        self.assertLoggedIn("default content", "Do not repeat the Speaker> line", content)


class TestSpeakerGating(LoggedTestCase):
    def test_speakers_detected(self):
        """Batches with speaker metadata qualify for speaker instructions."""
        lines = [_line(1, "hello", "Amina"), _line(2, "hi")]

        self.assertLoggedEqual("has speakers", True, LinesHaveSpeakers(lines))

    def test_no_speakers_detected(self):
        """Plain batches skip the speaker instructions."""
        lines = [_line(1, "hello"), _line(2, "hi")]

        self.assertLoggedEqual("no speakers", False, LinesHaveSpeakers(lines))
        self.assertLoggedEqual("empty batch", False, LinesHaveSpeakers([]))


class TestSpeakerParsing(LoggedTestCase):

    def _parser(self) -> TranslationParser:
        return TranslationParser("Translation", Options())

    def test_strip_helper(self):
        """Echoed speaker lines strip; other text is untouched."""
        self.assertLoggedEqual("stripped", "hello", _strip_speaker_prefix("Speaker> Amina\nhello"))
        self.assertLoggedEqual("case-insensitive", "hello", _strip_speaker_prefix("speaker> Amina\nhello"))
        self.assertLoggedEqual("untouched", "hello", _strip_speaker_prefix("hello"))
        self.assertLoggedEqual("none safe", None, _strip_speaker_prefix(None))

    def test_echoed_speaker_stripped_from_matches(self):
        """Speakers echoed inside blocks never reach subtitles or fuzzy matching."""
        parser = self._parser()
        response = ("#200\nOriginal>\nSpeaker> Amina\nhello\n"
                    "Translation>\nSpeaker> Amina\nhola\n\n")

        matches = parser.FindMatches(response + "\n", parser.regex_patterns[0])

        self.assertLoggedEqual("one match", 1, len(matches))
        self.assertLoggedEqual("clean body", "hola", (matches[0]['body'] or "").strip())
        self.assertLoggedEqual("clean original", "hello", (matches[0]['original'] or "").strip())

    def test_structural_echo_parses(self):
        """Speakers echoed after the line number still parse cleanly."""
        parser = self._parser()
        response = ("#200\nSpeaker> Amina\nOriginal>\nhello\n"
                    "Translation>\nhola\n\n"
                    "#201\nspeaker> Boris\nOriginal>\nhi\n"
                    "Translation>\nSpeaker> Boris\ney\n\n")

        matches = parser.FindMatches(response + "\n", parser.regex_patterns[0])

        self.assertLoggedEqual("two matches", 2, len(matches))
        self.assertLoggedEqual("first body", "hola", (matches[0]['body'] or "").strip())
        self.assertLoggedEqual("first original", "hello", (matches[0]['original'] or "").strip())
        self.assertLoggedEqual("second body", "ey", (matches[1]['body'] or "").strip())

    def test_speaker_without_original_parses(self):
        """An echoed speaker without an echoed original still parses."""
        parser = self._parser()
        response = "#200\nSpeaker> Amina\nTranslation>\nhola\n\n"

        matches = parser.FindMatches(response + "\n", parser.regex_patterns[0])

        self.assertLoggedEqual("one match", 1, len(matches))
        self.assertLoggedEqual("body", "hola", (matches[0]['body'] or "").strip())


if __name__ == '__main__':
    unittest.main()
