from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.SubtitleError import SubtitleError, TranslationImpossibleError


class TestSubtitleErrorReporting(LoggedTestCase):
    """A wrapped error must keep its cause and report it, or the user cannot act on it."""

    def test_translation_impossible_error_retains_the_cause(self) -> None:
        cause = ValueError("model not found")
        error = TranslationImpossibleError("Unexpected error communicating with server", error=cause)

        self.assertLoggedIs("cause retained", cause, error.error)
        self.assertLoggedIsNone("translation slot not used for the cause", error.translation)

    def test_str_reports_message_and_cause(self) -> None:
        error = TranslationImpossibleError("Unexpected error communicating with server", error=ValueError("model not found"))
        rendered = str(error)

        self.assertLoggedIn("context retained", "Unexpected error communicating with server", rendered)
        self.assertLoggedIn("cause reported", "model not found", rendered)

    def test_str_does_not_repeat_the_cause(self) -> None:
        error = TranslationImpossibleError("Model not found", error=ValueError("Model not found"))

        self.assertLoggedEqual("cause not duplicated", "Model not found", str(error))

    def test_str_falls_back_to_the_exception_type(self) -> None:
        error = TranslationImpossibleError("Connection failed", error=TimeoutError())

        self.assertLoggedIn("exception type named", "TimeoutError", str(error))

    def test_str_without_message_or_cause(self) -> None:
        error = SubtitleError()

        self.assertLoggedIsInstance("renders as a string", str(error), str)
