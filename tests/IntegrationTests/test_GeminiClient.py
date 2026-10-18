import importlib.util
import itertools
import logging
import unittest
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.SettingsType import SettingsType
from PySubtrans.Translation import Translation
from PySubtrans.TranslationPrompt import TranslationPrompt
from PySubtrans.TranslationRequest import TranslationRequest

HAS_GEMINI = importlib.util.find_spec("google.genai") is not None

if HAS_GEMINI:
    from google.genai.types import Candidate, Content, FinishReason, GenerateContentConfig, GenerateContentResponse, Part, ThinkingLevel

    from PySubtrans.Providers.Clients.GeminiClient import GeminiClient
    from PySubtrans.Providers.Provider_Gemini import DEFAULT_THINKING_LEVEL

_MODULE = 'PySubtrans.Providers.Clients.GeminiClient'

_PROMPT_CONTENT = "#1\nOriginal>\n안녕하세요\nTranslation>\n\n#2\nOriginal>\n잘 가요\nTranslation>\n"
_RESPONSE_BLOCK = "#1\nOriginal>\n안녕하세요\nTranslation>\nHello\n\n"


def _create_client(timeout : int = 0, max_retries : int = 0, extra_settings : dict[str, str|bool|float]|None = None) -> 'GeminiClient':
    """Create a streaming Gemini client with a placeholder key."""
    settings = SettingsType({
        'api_key': 'test-key',
        'instructions': 'Translate the subtitles.',
        'model': 'gemini-test',
        'supports_streaming': True,
        'stream_responses': True,
        'max_retries': max_retries,
        'backoff_time': 0.01,
        'timeout': timeout
    })
    settings.update(extra_settings or {})
    return GeminiClient(settings)


def _create_request() -> TranslationRequest:
    """Create a streaming request for a two-line batch."""
    prompt = TranslationPrompt("Translate this", conversation=False)
    prompt.system_prompt = "Translate the subtitles."
    prompt.content = _PROMPT_CONTENT
    return TranslationRequest(prompt, streaming_callback=lambda _translation: None)


def _chunk(text : str|None, finish_reason : 'FinishReason|None' = None) -> 'GenerateContentResponse':
    """Build a streamed chunk, with no content parts when text is None."""
    content = Content(role="model", parts=[Part.from_text(text=text)]) if text is not None else None
    return GenerateContentResponse(candidates=[Candidate(content=content, finish_reason=finish_reason)])


def _mock_genai_client(chunks : Iterator['GenerateContentResponse']) -> MagicMock:
    """Return a genai.Client replacement whose stream yields the given chunks."""
    genai_client = MagicMock()
    genai_client.models.generate_content_stream.return_value = chunks
    return MagicMock(return_value=genai_client)


@unittest.skipUnless(HAS_GEMINI, "google-genai SDK is not installed")
class TestGeminiClientStreaming(LoggedTestCase):
    """Tests for how the Gemini client ends a streamed response."""

    def test_complete_stream(self) -> None:
        """A stream that finishes normally is reported as complete."""
        client = _create_client()
        chunks = iter([_chunk(_RESPONSE_BLOCK), _chunk(None, FinishReason.STOP)])

        with patch(f'{_MODULE}.genai.Client', _mock_genai_client(chunks)):
            translation = client._request_translation(_create_request())

        self.assertLoggedIsInstance("translation", translation, Translation)
        if translation:
            self.assertLoggedEqual("finish reason", "complete", translation.finish_reason)

    def test_token_limit_on_empty_final_chunk(self) -> None:
        """A token limit reported on a final chunk without parts is not lost."""
        client = _create_client()
        chunks = iter([_chunk(_RESPONSE_BLOCK), _chunk(None, FinishReason.MAX_TOKENS)])

        with patch(f'{_MODULE}.genai.Client', _mock_genai_client(chunks)):
            with self.assertLogs(level=logging.WARNING):
                translation = client._request_translation(_create_request())

        self.assertLoggedIsNotNone("translation", translation)
        if translation:
            self.assertLoggedTrue("reached token limit", translation.reached_token_limit)
            self.assertLoggedIsNotNone("partial text kept", translation.text)

    def test_slow_stream_is_stopped_at_timeout(self) -> None:
        """A stream that runs past the timeout is cut off and its partial text returned."""
        client = _create_client(timeout=120)
        chunks_consumed = 0
        clock = itertools.count(0.0, 45.0)

        def endless_chunks() -> Iterator['GenerateContentResponse']:
            nonlocal chunks_consumed
            while True:
                chunks_consumed += 1
                yield _chunk(_RESPONSE_BLOCK)

        with patch(f'{_MODULE}.genai.Client', _mock_genai_client(endless_chunks())):
            with patch(f'{_MODULE}.time.monotonic', side_effect=lambda: next(clock)):
                with self.assertLogs(level=logging.WARNING):
                    translation = client._request_translation(_create_request())

        self.assertLoggedIsNotNone("translation", translation)
        if translation:
            self.assertLoggedEqual("finish reason", "timeout", translation.finish_reason)
            self.assertLoggedIsNotNone("partial text kept", translation.text)

        self.assertLoggedLess("chunks consumed", chunks_consumed, 10)

    def test_timeout_without_text_is_not_retried(self) -> None:
        """A stream that times out before any visible text fails without resending the request."""
        client = _create_client(timeout=120, max_retries=1)
        clock = itertools.count(0.0, 45.0)

        def thinking_chunks() -> Iterator['GenerateContentResponse']:
            while True:
                thought = Part.from_text(text="Thinking...")
                thought.thought = True
                yield GenerateContentResponse(candidates=[Candidate(content=Content(role="model", parts=[thought]))])

        genai_client = MagicMock()
        genai_client.models.generate_content_stream.return_value = thinking_chunks()

        with patch(f'{_MODULE}.genai.Client', MagicMock(return_value=genai_client)):
            with patch(f'{_MODULE}.time.monotonic', side_effect=lambda: next(clock)):
                with self.assertLogs(level=logging.WARNING):
                    translation = client._request_translation(_create_request())

        self.assertLoggedIsNone("translation", translation)
        self.assertLoggedEqual("stream requests", 1, genai_client.models.generate_content_stream.call_count)

    def test_timeout_passed_to_sdk(self) -> None:
        """The timeout also bounds the SDK request, in milliseconds."""
        client = _create_client(timeout=120)
        chunks = iter([_chunk(_RESPONSE_BLOCK), _chunk(None, FinishReason.STOP)])
        mock_client_class = _mock_genai_client(chunks)

        with patch(f'{_MODULE}.genai.Client', mock_client_class):
            client._request_translation(_create_request())

        http_options = mock_client_class.call_args.kwargs.get('http_options')
        self.assertLoggedEqual("sdk timeout", 120000, getattr(http_options, 'timeout', None))

    def test_retry_after_failed_stream_starts_afresh(self) -> None:
        """Text from a stream that failed part way is not carried into the retry."""
        client = _create_client(max_retries=1)

        def failing_chunks() -> Iterator['GenerateContentResponse']:
            yield _chunk(_RESPONSE_BLOCK)
            raise ConnectionError("Simulated stream failure")

        genai_client = MagicMock()
        genai_client.models.generate_content_stream.side_effect = [
            failing_chunks(),
            iter([_chunk(_RESPONSE_BLOCK), _chunk(None, FinishReason.STOP)])
        ]

        with patch(f'{_MODULE}.genai.Client', MagicMock(return_value=genai_client)):
            with self.assertLogs(level=logging.WARNING):
                translation = client._request_translation(_create_request())

        self.assertLoggedIsNotNone("translation", translation)
        if translation and translation.text:
            self.assertLoggedEqual("line blocks in response", 1, translation.text.count("#1"))

    def test_progress_reported_during_long_stream(self) -> None:
        """A long stream reports progress while it is still arriving."""
        client = _create_client()
        chunks = iter([_chunk(_RESPONSE_BLOCK), _chunk(_RESPONSE_BLOCK), _chunk(None, FinishReason.STOP)])
        clock = itertools.count(0.0, 45.0)

        with patch(f'{_MODULE}.genai.Client', _mock_genai_client(chunks)):
            with patch(f'{_MODULE}.time.monotonic', side_effect=lambda: next(clock)):
                with self.assertLogs(level=logging.INFO) as logs:
                    client._request_translation(_create_request())

        info_records = [record for record in logs.records if record.levelno == logging.INFO]
        self.assertLoggedGreater("progress messages", len(info_records), 0)


@unittest.skipUnless(HAS_GEMINI, "google-genai SDK is not installed")
class TestGeminiClientGenerationConfig(LoggedTestCase):
    """Tests for the generation parameters the Gemini client sends."""

    def _get_sent_config(self, client : 'GeminiClient', temperature : float|None = None) -> 'GenerateContentConfig|None':
        """Send a request and return the config passed to the SDK."""
        chunks = iter([_chunk(_RESPONSE_BLOCK), _chunk(None, FinishReason.STOP)])
        mock_client_class = _mock_genai_client(chunks)

        with patch(f'{_MODULE}.genai.Client', mock_client_class):
            client._request_translation(_create_request(), temperature)

        return mock_client_class.return_value.models.generate_content_stream.call_args.kwargs.get('config')

    def test_thinking_level_sent_instead_of_budget(self) -> None:
        """Thinking is configured by level, which future models require."""
        client = _create_client(extra_settings={'thinking_level': "medium"})
        config = self._get_sent_config(client)

        thinking_config = config.thinking_config if config else None
        self.assertLoggedIsNotNone("thinking config", thinking_config)
        if thinking_config:
            self.assertLoggedEqual("thinking level", ThinkingLevel.MEDIUM, thinking_config.thinking_level)
            self.assertLoggedIsNone("thinking budget", thinking_config.thinking_budget)

    def test_default_level_uses_model_default(self) -> None:
        """No thinking config is sent when the level is left to the model."""
        client = _create_client(extra_settings={'thinking_level': DEFAULT_THINKING_LEVEL})
        config = self._get_sent_config(client)

        self.assertLoggedIsNotNone("config", config)
        if config:
            self.assertLoggedIsNone("thinking config", config.thinking_config)

    def test_unknown_thinking_level_uses_model_default(self) -> None:
        """An unrecognised level is not sent to the API."""
        with self.assertLogs(level=logging.WARNING):
            client = _create_client(extra_settings={'thinking_level': "extreme"})

        config = self._get_sent_config(client)

        self.assertLoggedIsNotNone("config", config)
        if config:
            self.assertLoggedIsNone("thinking config", config.thinking_config)

    def test_sampling_parameters_not_sent(self) -> None:
        """Temperature and other sampling parameters are omitted, even on a retry that asks for one."""
        client = _create_client(extra_settings={'temperature': 0.5})
        config = self._get_sent_config(client, temperature=0.6)

        self.assertLoggedIsNotNone("config", config)
        if config:
            self.assertLoggedIsNone("temperature", config.temperature)
            self.assertLoggedIsNone("top_p", config.top_p)
            self.assertLoggedIsNone("top_k", config.top_k)


if __name__ == '__main__':
    unittest.main()
