from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Options import Options
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.SubtitleValidator import SubtitleValidator
from PySubtrans.ValidationError import (
    UnmatchedLinesError,
    EmptyLinesError,
    ExcessiveDurationError,
    LineTooLongError,
    TooManyNewlinesError,
    UntranslatedLinesError,
)


class TestSubtitleValidator(LoggedTestCase):
    def test_ValidateTranslations_empty(self):
        validator = SubtitleValidator(Options())
        errors = validator.ValidateTranslations([])
        self.assertLoggedEqual("error_count", 1, len(errors))
        self.assertLoggedIsInstance("error type", errors[0], UntranslatedLinesError)

    def test_ValidateTranslations_detects_errors(self):
        options = Options({'max_characters': 10, 'max_newlines': 1})
        validator = SubtitleValidator(options)

        line_no_number = SubtitleLine({'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'valid'})
        line_no_text = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:01,000'})
        line_too_long = SubtitleLine({'number': 2, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'abcdefghijklmnopqrstuvwxyz'})
        line_too_many_newlines = SubtitleLine({'number': 3, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'a\nb\nc'})

        errors = validator.ValidateTranslations([line_no_number, line_no_text, line_too_long, line_too_many_newlines])
        expected_types = [UnmatchedLinesError, EmptyLinesError, LineTooLongError, TooManyNewlinesError]
        self.assertLoggedEqual("error_count", len(expected_types), len(errors))

        actual_error_types = {type(e) for e in errors}
        expected_error_types = set(expected_types)
        self.assertLoggedEqual("error types", expected_error_types, actual_error_types)

    def test_ValidateBatch_adds_untranslated_error(self):
        validator = SubtitleValidator(Options())

        orig1 = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'original1'})
        orig2 = SubtitleLine({'number': 2, 'start': '00:00:01,000', 'end': '00:00:02,000', 'text': 'original2'})
        trans1 = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'translated1'})
        batch = SubtitleBatch({'originals': [orig1, orig2], 'translated': [trans1]})

        validator.ValidateBatch(batch)
        self.assertLoggedEqual("error_count", 1, len(batch.errors))
        self.assertLoggedIsInstance("error type", batch.errors[0], UntranslatedLinesError)

    def test_ValidateBatch_includes_translation_errors(self):
        options = Options({'max_characters': 10})
        validator = SubtitleValidator(options)

        orig1 = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'original1'})
        orig2 = SubtitleLine({'number': 2, 'start': '00:00:01,000', 'end': '00:00:02,000', 'text': 'original2'})
        # This translated line is too long
        trans1 = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'this is a very long translated line'})
        batch = SubtitleBatch({'originals': [orig1, orig2], 'translated': [trans1]})

        validator.ValidateBatch(batch)

        self.assertLoggedEqual("batch error types", {UntranslatedLinesError}, {type(e) for e in batch.errors})
        self.assertLoggedEqual("batch warning types", {LineTooLongError}, {type(e) for e in batch.warnings})

    def test_ValidateBatch_minor_issues_are_warnings(self):
        options = Options({'max_characters': 10, 'max_newlines': 1})
        validator = SubtitleValidator(options)

        orig1 = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'original1'})
        orig2 = SubtitleLine({'number': 2, 'start': '00:00:01,000', 'end': '00:00:02,000', 'text': 'original2'})
        trans1 = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'this is a very long translated line'})
        trans2 = SubtitleLine({'number': 2, 'start': '00:00:01,000', 'end': '00:00:02,000', 'text': 'a\nb\nc'})
        batch = SubtitleBatch({'originals': [orig1, orig2], 'translated': [trans1, trans2]})

        validator.ValidateBatch(batch)

        self.assertLoggedEqual("error_count", 0, len(batch.errors))
        self.assertLoggedEqual("batch warning types", {LineTooLongError, TooManyNewlinesError}, {type(e) for e in batch.warnings})
        self.assertLoggedTrue("batch with only warnings is complete", batch.translation_complete)

        long_line_warning = next(w for w in batch.warnings if isinstance(w, LineTooLongError))
        self.assertLoggedEqual("warning records line numbers", [1], long_line_warning.line_numbers)

    def test_ValidateBatch_warnings_as_errors(self):
        options = Options({'max_characters': 10, 'warnings_as_errors': True})
        validator = SubtitleValidator(options)

        orig1 = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'original1'})
        trans1 = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'this is a very long translated line'})
        batch = SubtitleBatch({'originals': [orig1], 'translated': [trans1]})

        validator.ValidateBatch(batch)

        self.assertLoggedEqual("batch error types", {LineTooLongError}, {type(e) for e in batch.errors})
        self.assertLoggedEqual("warning_count", 0, len(batch.warnings))
        self.assertLoggedFalse("batch with errors is incomplete", batch.translation_complete)

    def test_ValidateBatch_clears_resolved_warnings(self):
        options = Options({'max_characters': 10})
        validator = SubtitleValidator(options)

        orig1 = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'original1'})
        trans1 = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'this is a very long translated line'})
        batch = SubtitleBatch({'originals': [orig1], 'translated': [trans1]})

        validator.ValidateBatch(batch)
        self.assertLoggedEqual("warning_count before edit", 1, len(batch.warnings))

        batch.translated[0].text = 'short'
        validator.ValidateBatch(batch)
        self.assertLoggedEqual("warning_count after edit", 0, len(batch.warnings))

    def test_zero_max_characters_means_no_limit(self):
        options = Options({'max_characters': 0})
        validator = SubtitleValidator(options)

        line = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'x' * 2000})
        errors = validator.ValidateTranslations([line])
        self.assertLoggedEqual("error_count", 0, len(errors))

    def test_zero_max_newlines_allows_no_newlines(self):
        options = Options({'max_newlines': 0})
        validator = SubtitleValidator(options)

        line = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'one\ntwo'})
        errors = validator.ValidateTranslations([line])
        self.assertLoggedEqual("error types", {TooManyNewlinesError}, {type(e) for e in errors})


class TestValidateOriginals(LoggedTestCase):
    def test_empty_list(self):
        validator = SubtitleValidator(Options())
        errors = validator.ValidateOriginals([], 8.0)
        self.assertLoggedEqual("error_count", 0, len(errors))

    def test_detects_buckets(self):
        options = Options({'max_characters': 10, 'max_newlines': 1})
        validator = SubtitleValidator(options)

        line_blank = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:01,000'})
        line_too_long = SubtitleLine({'number': 2, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'abcdefghijklmnopqrstuvwxyz'})
        line_too_many_newlines = SubtitleLine({'number': 3, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'a\nb\nc'})
        line_overlong = SubtitleLine({'number': 4, 'start': '00:00:00,000', 'end': '00:00:20,000', 'text': 'ok'})

        errors = validator.ValidateOriginals([line_blank, line_too_long, line_too_many_newlines, line_overlong], 8.0)
        expected_types = [EmptyLinesError, LineTooLongError, TooManyNewlinesError, ExcessiveDurationError]
        self.assertLoggedEqual("error_count", len(expected_types), len(errors))

        actual_error_types = {type(e) for e in errors}
        expected_error_types = set(expected_types)
        self.assertLoggedEqual("error types", expected_error_types, actual_error_types)

    def test_clean_lines_pass(self):
        validator = SubtitleValidator(Options())
        line = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'hello'})
        errors = validator.ValidateOriginals([line], 8.0)
        self.assertLoggedEqual("error_count", 0, len(errors))

    def test_ValidateBatch_flagged_validates_originals(self):
        validator = SubtitleValidator(Options())

        orig = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:20,000', 'text': 'ok'})
        batch = SubtitleBatch({'originals': [orig], 'translated': []})
        batch.validate_originals = True

        validator.ValidateBatch(batch)
        self.assertLoggedEqual("error_count", 0, len(batch.errors))
        self.assertLoggedEqual("batch warning types", {ExcessiveDurationError}, {type(e) for e in batch.warnings})

    def test_ValidateBatch_zero_max_duration_means_no_limit(self):
        validator = SubtitleValidator(Options({'max_line_duration': 0.0}))

        orig = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:20,000', 'text': 'ok'})
        batch = SubtitleBatch({'originals': [orig], 'translated': []})
        batch.validate_originals = True

        validator.ValidateBatch(batch)
        self.assertLoggedEqual("error_count", 0, len(batch.errors))

    def test_ValidateBatch_unflagged_skips_originals(self):
        validator = SubtitleValidator(Options())

        orig = SubtitleLine({'number': 1, 'start': '00:00:00,000', 'end': '00:00:20,000', 'text': 'ok'})
        batch = SubtitleBatch({'originals': [orig], 'translated': []})

        validator.ValidateBatch(batch)
        self.assertLoggedEqual("error_count", 0, len(batch.errors))
