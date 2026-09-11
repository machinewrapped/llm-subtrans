import unittest
from unittest.mock import Mock

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Translation import Translation
from scripts.subtrans_common import LogTranslationStatus, TokenUsage


class TestTokenUsage(LoggedTestCase):
    """Tests for accumulating and logging provider-reported translation cost."""

    def test_cost_accumulates_across_batches(self) -> None:
        """Reported batch costs are added to the translation total."""
        usage = TokenUsage()
        usage.Add({'prompt_tokens': 10, 'output_tokens': 20, 'cost': 0.0012})
        usage.Add({'prompt_tokens': 30, 'output_tokens': 40, 'cost': 0.0034})

        self.assertLoggedEqual("prompt token total", 40, usage.prompt_tokens)
        self.assertLoggedEqual("output token total", 60, usage.output_tokens)
        self.assertLoggedEqual("translation cost total", 0.0046, usage.cost)

    def test_cost_is_logged_in_translation_status(self) -> None:
        """A reported total appears in the final translation status log."""
        usage = TokenUsage(cost=0.0046)
        subtitles = Mock(linecount=2, translated=[object()])
        project = Mock(subtitles=subtitles, all_translated=True)

        with self.assertLogs(level='INFO') as captured:
            LogTranslationStatus(project, token_usage=usage)

        self.assertLoggedTrue(
            "translation cost log",
            any("Translation cost: $0.0046" in message for message in captured.output),
        )

    def test_cost_is_in_formatted_translation_metadata(self) -> None:
        """The GUI response formatter exposes provider-reported cost metadata."""
        translation = Translation({'text': 'translated text', 'cost': 0.0042})

        self.assertLoggedEqual('pre-formatted cost metadata', '$0.0042', translation.content.get('cost'))
        self.assertLoggedIn('formatted cost metadata', 'cost: $0.0042', translation.FormatResponse())


if __name__ == '__main__':
    unittest.main()
