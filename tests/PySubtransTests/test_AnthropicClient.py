import importlib.util
import unittest
from unittest.mock import MagicMock

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.SettingsType import SettingsType
from PySubtrans.TranslationPrompt import TranslationPrompt
from PySubtrans.TranslationRequest import TranslationRequest

HAS_ANTHROPIC = importlib.util.find_spec("anthropic") is not None

if HAS_ANTHROPIC:
    from PySubtrans.Providers.Clients.AnthropicClient import AnthropicClient


def _create_test_settings(model : str, thinking : bool = False) -> SettingsType:
    """Create minimal Anthropic client settings for testing."""
    return SettingsType({
        'api_key': 'test-key',
        'instructions': 'Translate the subtitles.',
        'model': model,
        'max_tokens': 512,
        'thinking': thinking
    })


def _create_test_request() -> TranslationRequest:
    """Create a minimal Anthropic translation request for testing."""
    prompt = TranslationPrompt("Translate this", conversation=True)
    prompt.system_prompt = "Translate the subtitles."
    prompt.content = [{'role': 'user', 'content': 'Hello world'}]
    return TranslationRequest(prompt)


@unittest.skipUnless(HAS_ANTHROPIC, "anthropic SDK is not installed")
class TestAnthropicClientRequestParameters(LoggedTestCase):
    """Tests for Anthropic model-specific request parameters."""

    def test_opus_4_7_omits_temperature(self) -> None:
        """Opus 4.7 request payloads omit deprecated temperature."""
        client = AnthropicClient(_create_test_settings('claude-opus-4-7'))
        client.client = MagicMock()

        client._create_client_response(_create_test_request().prompt, 0.3)
        kwargs = client.client.messages.create.call_args.kwargs

        self.assertLoggedNotIn("temperature omitted", 'temperature', kwargs)

    def test_older_opus_models_keep_temperature(self) -> None:
        """Older Opus models still include temperature in request payloads."""
        client = AnthropicClient(_create_test_settings('claude-opus-4-6'))
        client.client = MagicMock()

        client._create_client_response(_create_test_request().prompt, 0.3)
        kwargs = client.client.messages.create.call_args.kwargs

        self.assertLoggedEqual("temperature", 0.3, kwargs.get('temperature'))

    def test_dated_opus_4_keeps_temperature(self) -> None:
        """Dated Opus 4 snapshot IDs (e.g. claude-opus-4-20250514) must not drop temperature."""
        client = AnthropicClient(_create_test_settings('claude-opus-4-20250514'))
        client.client = MagicMock()

        client._create_client_response(_create_test_request().prompt, 0.3)
        kwargs = client.client.messages.create.call_args.kwargs

        self.assertLoggedEqual("temperature", 0.3, kwargs.get('temperature'))

    def test_dated_opus_4_7_omits_temperature(self) -> None:
        """Dated Opus 4.7 snapshot IDs (e.g. claude-opus-4-7-20250514) still omit temperature."""
        client = AnthropicClient(_create_test_settings('claude-opus-4-7-20250514'))
        client.client = MagicMock()

        client._create_client_response(_create_test_request().prompt, 0.3)
        kwargs = client.client.messages.create.call_args.kwargs

        self.assertLoggedNotIn("temperature omitted", 'temperature', kwargs)

    def test_opus_4_7_thinking_uses_adaptive_mode(self) -> None:
        """Opus 4.7 thinking mode uses adaptive thinking without a budget."""
        client = AnthropicClient(_create_test_settings('Claude Opus 4.7', thinking=True))
        client.client = MagicMock()

        client._create_client_response(_create_test_request().prompt, 0.3)
        kwargs = client.client.messages.create.call_args.kwargs
        thinking = kwargs.get('thinking', {})

        self.assertLoggedEqual("thinking type", 'adaptive', thinking.get('type'))
        self.assertLoggedNotIn("budget tokens omitted", 'budget_tokens', thinking)
