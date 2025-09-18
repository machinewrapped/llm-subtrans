import unittest

from PySubtrans.Helpers.Tests import log_input_expected_error, log_input_expected_result, log_test_name
from PySubtrans.Options import Options
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.SubtitleValidator import SubtitleValidator
from PySubtrans.SubtitleError import (
    UnmatchedLinesError,
    EmptyLinesError,
    LineTooLongError,
    TooManyNewlinesError,
    UntranslatedLinesError,
)


class TestSubtitleValidator(unittest.TestCase):
    def test_ValidateTranslations_empty(self):
        log_test_name("ValidateTranslationsEmpty")
        validator = SubtitleValidator(Options())
        errors = validator.ValidateTranslations([])
        log_input_expected_result("error_count", 1, len(errors))
        self.assertEqual(len(errors), 1)
        log_input_expected_error(errors[0], UntranslatedLinesError, errors[0])
        self.assertEqual(type(errors[0]), UntranslatedLinesError)

    def test_ValidateTranslations_detects_errors(self):
        log_test_name("ValidateTranslationsDetectsErrors")
        options = Options({'max_characters': 10, 'max_newlines': 1})
        validator = SubtitleValidator(options)

        line_no_number = SubtitleLine({'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'valid'})
        line_no_text = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:01,000'})
        line_too_long = SubtitleLine({'number': 2, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'abcdefghijklmnopqrstuvwxyz'})
        line_too_many_newlines = SubtitleLine({'number': 3, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'a\nb\nc'})

        errors = validator.ValidateTranslations([line_no_number, line_no_text, line_too_long, line_too_many_newlines])
        expected_types = [UnmatchedLinesError, EmptyLinesError, LineTooLongError, TooManyNewlinesError]
        log_input_expected_result("error_count", len(expected_types), len(errors))
        self.assertEqual(len(errors), len(expected_types))

        actual_error_types = {type(e) for e in errors}
        expected_error_types = set(expected_types)
        log_input_expected_result("error types", expected_error_types, actual_error_types)
        self.assertEqual(actual_error_types, expected_error_types)

    def test_ValidateBatch_adds_untranslated_error(self):
        log_test_name("ValidateBatchAddsUntranslatedError")
        validator = SubtitleValidator(Options())

        orig1 = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'original1'})
        orig2 = SubtitleLine({'number': 2, 'start': '00:00:01,000', 'end': '00:00:02,000', 'text': 'original2'})
        trans1 = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'translated1'})
        batch = SubtitleBatch({'originals': [orig1, orig2], 'translated': [trans1]})

        validator.ValidateBatch(batch)
        log_input_expected_result("error_count", 1, len(batch.errors))
        self.assertEqual(len(batch.errors), 1)
        log_input_expected_error(batch.errors[0], UntranslatedLinesError, batch.errors[0])
        self.assertEqual(type(batch.errors[0]), UntranslatedLinesError)

    def test_ValidateBatch_includes_translation_errors(self):
        log_test_name("ValidateBatchIncludesTranslationErrors")
        options = Options({'max_characters': 10})
        validator = SubtitleValidator(options)

        orig1 = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'original1'})
        orig2 = SubtitleLine({'number': 2, 'start': '00:00:01,000', 'end': '00:00:02,000', 'text': 'original2'})
        # This translated line is too long
        trans1 = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'this is a very long translated line'})
        batch = SubtitleBatch({'originals': [orig1, orig2], 'translated': [trans1]})

        validator.ValidateBatch(batch)

        error_types = {type(e) for e in batch.errors}
        log_input_expected_result("batch error types", {LineTooLongError, UntranslatedLinesError}, error_types)
        self.assertIn(LineTooLongError, error_types)
        self.assertIn(UntranslatedLinesError, error_types)