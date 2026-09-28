from unittest.mock import Mock, patch

from PySubtrans.Helpers.TestCases import DummyProvider, LoggedTestCase
from PySubtrans.Options import Options
from PySubtrans.SubtitleTranslator import SubtitleTranslator
from PySubtrans.Translation import Translation
from scripts.subtrans_common import TranslationProgressLogger


class TestTranslationProgress(LoggedTestCase):
    """Tests for the command-line translation progress logger."""

    def test_usage_counts_every_translation_request(self) -> None:
        """The cost of retries and other additional provider requests reaches the command-line total."""
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

        self.assertLoggedEqual("all request costs reported to the command-line total", 0.0046, progress_logger.token_usage.cost)
