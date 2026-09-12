import json
import unittest
from unittest.mock import Mock, patch

from PySubtrans.Helpers.TestCases import DummyProvider, LoggedTestCase
from PySubtrans.Options import Options
from PySubtrans.SubtitleSerialisation import SubtitleDecoder, SubtitleEncoder
from PySubtrans.SubtitleTranslator import SubtitleTranslator
from PySubtrans.Subtitles import Subtitles
from PySubtrans.Translation import Translation
from scripts.subtrans_common import LogTranslationStatus, TokenUsage, TranslationProgressLogger


class TestTranslationCost(LoggedTestCase):
    """Tests for accumulating and logging provider-reported translation cost."""

    def test_cost_accumulates_across_batches(self) -> None:
        """Reported batch costs are added to the translation total."""
        usage = TokenUsage()
        usage.Add({'prompt_tokens': 10, 'output_tokens': 20})
        usage.Add({'prompt_tokens': 30, 'output_tokens': 40})
        usage.AddCost(0.0012)
        usage.AddCost(0.0034)

        self.assertLoggedEqual("prompt token total", 40, usage.prompt_tokens)
        self.assertLoggedEqual("output token total", 60, usage.output_tokens)
        self.assertLoggedEqual("translation cost total", 0.0046, usage.cost)

    def test_cli_usage_accumulates_every_translation_request(self) -> None:
        """CLI usage includes retries and other additional provider requests."""
        translator = SubtitleTranslator(Options(), DummyProvider(data={}))
        progress_logger = TranslationProgressLogger()
        prompt = Mock()
        responses = [
            Translation({'text': 'first response', 'cost': 0.0012}),
            Translation({'text': 'retry response', 'cost': 0.0034}),
        ]

        with progress_logger.Track(translator):
            with patch.object(translator.client, '_request_translation', side_effect=responses):
                translator.client.RequestTranslation(prompt)
                translator.client.RequestTranslation(prompt)

        self.assertLoggedEqual("all request costs reported to CLI usage", 0.0046, progress_logger.token_usage.cost)

    def test_subtitles_accumulates_cost_across_translation_passes(self) -> None:
        """The project-level total survives repeated translation passes."""
        subtitles = Subtitles()
        subtitles.AddTranslationCost(0.0012)
        subtitles.AddTranslationCost(0.0034)

        self.assertLoggedEqual("project translation cost total", 0.0046, subtitles.translation_cost)

    def test_subtitles_cost_survives_project_serialisation(self) -> None:
        """The cumulative project total is retained in project files."""
        subtitles = Subtitles()
        subtitles.AddTranslationCost(0.0046)

        restored = json.loads(json.dumps(subtitles, cls=SubtitleEncoder), cls=SubtitleDecoder)

        self.assertLoggedEqual("serialised project translation cost", 0.0046, restored.translation_cost)

    def test_cost_is_logged_in_translation_status(self) -> None:
        """The CLI run total appears in the final status log."""
        usage = TokenUsage(cost=0.0046)
        subtitles = Mock(linecount=2, translated=[object()], translation_cost=None)
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
