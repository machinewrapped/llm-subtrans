import importlib.util
import unittest
from unittest.mock import MagicMock

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.SettingsType import SettingsType
from PySubtrans.TranslationPrompt import TranslationPrompt
from PySubtrans.TranslationRequest import TranslationRequest

HAS_ANTHROPIC = importlib.util.find_spec("anthropic") is not None

if HAS_ANTHROPIC:
    import anthropic

    from PySubtrans.Providers.Clients.AnthropicClient import AnthropicClient


def _create_test_settings(model : str, thinking : bool = False, **extra) -> SettingsType:
    """Create minimal Anthropic client settings for testing."""
    settings : dict = {
        'api_key': 'test-key',
        'instructions': 'Translate the subtitles.',
        'model': model,
        'max_tokens': 512,
        'thinking': thinking
    }
    settings.update(extra)
    return SettingsType(settings)


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

    def test_sonnet_5_omits_temperature(self) -> None:
        """Sonnet 5 request payloads omit deprecated temperature."""
        client = AnthropicClient(_create_test_settings('claude-sonnet-5'))
        client.client = MagicMock()

        client._create_client_response(_create_test_request().prompt, 0.3)
        kwargs = client.client.messages.create.call_args.kwargs

        self.assertLoggedNotIn("temperature omitted", 'temperature', kwargs)

    def test_fable_5_omits_temperature(self) -> None:
        """Fable 5 request payloads omit deprecated temperature."""
        client = AnthropicClient(_create_test_settings('claude-fable-5'))
        client.client = MagicMock()

        client._create_client_response(_create_test_request().prompt, 0.3)
        kwargs = client.client.messages.create.call_args.kwargs

        self.assertLoggedNotIn("temperature omitted", 'temperature', kwargs)

    def test_sonnet_5_thinking_uses_adaptive_mode(self) -> None:
        """Sonnet 5 thinking mode uses adaptive thinking without a budget."""
        client = AnthropicClient(_create_test_settings('claude-sonnet-5', thinking=True))
        client.client = MagicMock()

        client._create_client_response(_create_test_request().prompt, 0.3)
        kwargs = client.client.messages.create.call_args.kwargs
        thinking = kwargs.get('thinking', {})

        self.assertLoggedEqual("thinking type", 'adaptive', thinking.get('type'))
        self.assertLoggedNotIn("budget tokens omitted", 'budget_tokens', thinking)

    def test_opus_4_7_thinking_uses_adaptive_mode(self) -> None:
        """Opus 4.7 thinking mode uses adaptive thinking without a budget."""
        client = AnthropicClient(_create_test_settings('Claude Opus 4.7', thinking=True))
        client.client = MagicMock()

        client._create_client_response(_create_test_request().prompt, 0.3)
        kwargs = client.client.messages.create.call_args.kwargs
        thinking = kwargs.get('thinking', {})

        self.assertLoggedEqual("thinking type", 'adaptive', thinking.get('type'))
        self.assertLoggedNotIn("budget tokens omitted", 'budget_tokens', thinking)

    def test_unrecognized_model_omits_temperature(self) -> None:
        """Unidentifiable model names default to omitting temperature (assume it is gone)."""
        client = AnthropicClient(_create_test_settings('some-future-model'))
        client.client = MagicMock()

        client._create_client_response(_create_test_request().prompt, 0.3)
        kwargs = client.client.messages.create.call_args.kwargs

        self.assertLoggedNotIn("temperature omitted", 'temperature', kwargs)

    def test_capabilities_adaptive_only_uses_adaptive_mode(self) -> None:
        """Reported adaptive-only thinking capability selects adaptive mode."""
        client = AnthropicClient(_create_test_settings(
            'claude-sonnet-5', thinking=True,
            thinking_supports_adaptive=True, thinking_supports_enabled=False))
        client.client = MagicMock()

        client._create_client_response(_create_test_request().prompt, 0.3)
        thinking = client.client.messages.create.call_args.kwargs.get('thinking', {})

        self.assertLoggedEqual("thinking type", 'adaptive', thinking.get('type'))
        self.assertLoggedNotIn("budget tokens omitted", 'budget_tokens', thinking)

    def test_capabilities_override_version_heuristic(self) -> None:
        """Reported capabilities take precedence over the model-name version heuristic."""
        # An older model name that the heuristic would map to enabled thinking, but the
        # reported capabilities say adaptive-only - capabilities must win.
        client = AnthropicClient(_create_test_settings(
            'claude-opus-4-6', thinking=True,
            thinking_supports_adaptive=True, thinking_supports_enabled=False))
        client.client = MagicMock()

        client._create_client_response(_create_test_request().prompt, 0.3)
        thinking = client.client.messages.create.call_args.kwargs.get('thinking', {})

        self.assertLoggedEqual("thinking type", 'adaptive', thinking.get('type'))

    def test_capabilities_enabled_uses_budget_thinking(self) -> None:
        """A model reporting enabled thinking uses a token budget."""
        client = AnthropicClient(_create_test_settings(
            'claude-sonnet-4-6', thinking=True,
            thinking_supports_adaptive=True, thinking_supports_enabled=True))
        client.client = MagicMock()

        client._create_client_response(_create_test_request().prompt, 0.3)
        thinking = client.client.messages.create.call_args.kwargs.get('thinking', {})

        self.assertLoggedEqual("thinking type", 'enabled', thinking.get('type'))
        self.assertLoggedIn("budget tokens present", 'budget_tokens', thinking)

    def test_capabilities_no_thinking_omits_thinking(self) -> None:
        """A model that reports no thinking support omits the thinking parameter."""
        client = AnthropicClient(_create_test_settings(
            'claude-haiku-4-5', thinking=True,
            thinking_supports_adaptive=False, thinking_supports_enabled=False))
        client.client = MagicMock()

        client._create_client_response(_create_test_request().prompt, 0.3)
        thinking = client.client.messages.create.call_args.kwargs.get('thinking')

        self.assertLoggedIsInstance("thinking omitted", thinking, anthropic.Omit)
