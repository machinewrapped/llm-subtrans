from __future__ import annotations

import importlib.util
from typing import Any, cast
import unittest
from unittest.mock import PropertyMock, patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import log_input_expected_error, skip_if_debugger_attached
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import ProviderError, TranslationImpossibleError
from PySubtrans.TranslationPrompt import TranslationPrompt
from PySubtrans.TranslationRequest import TranslationRequest

_openai_available = importlib.util.find_spec("openai") is not None

if _openai_available:
    from openai.types import responses as responses_types
    from openai.types.responses import (
        ResponseCompletedEvent,
        ResponseError,
        ResponseFailedEvent,
        ResponseOutputMessage,
        ResponseOutputText,
    )
    import PySubtrans.Auth.ChatGPTAuth as chatgpt_auth_module
    from PySubtrans.Auth.ChatGPTAuth import API_RESOURCE, ChatGPTSignInOption, ChatGPTSignOutOption
    from PySubtrans.Providers.Clients.OpenAIReasoningClient import USAGE_LIMIT_EXCEEDED, OpenAIReasoningClient
    from PySubtrans.Providers.Provider_OpenAI import OpenAiProvider
    from tests.PySubtransTests.test_ChatGPTAuth import FakeChatGPTAuth, MemoryCredentialStore, SignedInStore


class FakeResponses:
    """Stands in for client.responses, recording the request and replaying stream events or a response."""
    def __init__(self, events : list[Any]):
        self.events = events
        self.kwargs : dict[str, Any] = {}

    def create(self, **kwargs : Any) -> Any:
        self.kwargs = kwargs
        return iter(self.events) if kwargs.get('stream') else MakeCompletedResponse()


class FakeOpenAI:
    def __init__(self, events : list[Any]):
        self.responses = FakeResponses(events)


def MakeCompletedResponse() -> Any:
    return responses_types.Response.model_construct(
        id="resp_test",
        object="response",
        status="completed",
        output=[
            ResponseOutputMessage.model_construct(
                id="msg_test",
                type="message",
                role="assistant",
                status="completed",
                content=[ResponseOutputText.model_construct(type="output_text", text="Bonjour.")]
            )
        ]
    )


def MakeRequest() -> TranslationRequest:
    """A request without a streaming callback, like a retranslation."""
    prompt = TranslationPrompt("Translate")
    prompt.system_prompt = "Translate the subtitles."
    prompt.content = [{'role': 'user', 'content': 'Hello.'}]
    return TranslationRequest(prompt)


@unittest.skipUnless(_openai_available, "openai package is not installed")
class OpenAIChatGPTPlanProviderTests(LoggedTestCase):
    """Tests for the OpenAI provider when it uses the ChatGPT plan."""

    def _create_provider(self, auth : FakeChatGPTAuth) -> OpenAiProvider:
        provider = OpenAiProvider(SettingsType({
            'use_chatgpt_plan': True,
            'model': 'gpt-plan',
            'api_base': 'https://custom.example/v1',
        }))
        patcher = patch.object(OpenAiProvider, 'chatgpt_auth', new_callable=PropertyMock, return_value=auth)
        patcher.start()
        self.addCleanup(patcher.stop)
        return provider

    def test_signed_out_offers_sign_in(self) -> None:
        provider = self._create_provider(FakeChatGPTAuth(MemoryCredentialStore()))

        options = provider.GetOptions(provider.settings)

        self.assertLoggedEqual('account option', ChatGPTSignInOption, options['chatgpt_account'][0])
        self.assertLoggedNotIn('api key option', 'api_key', options)
        self.assertLoggedFalse('settings valid', provider.ValidateSettings())

    def test_signed_in_offers_sign_out(self) -> None:
        provider = self._create_provider(FakeChatGPTAuth(SignedInStore()))

        options = provider.GetOptions(provider.settings)

        self.assertLoggedEqual('account option', ChatGPTSignOutOption, options['chatgpt_account'][0])
        self.assertLoggedNotIn('api key option', 'api_key', options)
        self.assertLoggedNotIn('stream option', 'stream_responses', options)
        self.assertLoggedTrue('settings valid', provider.ValidateSettings())

    def test_client_uses_access_token_on_public_api(self) -> None:
        """The client gets the access token as its API key, with plan usage request settings."""
        provider = self._create_provider(FakeChatGPTAuth(SignedInStore()))

        client = provider.GetTranslationClient(SettingsType({'instructions': 'Translate.'}))

        self.assertLoggedIsInstance('client type', client, OpenAIReasoningClient)
        self.assertLoggedEqual('api key', 'access-1', client.settings.get_str('api_key'))
        self.assertLoggedEqual('api base', API_RESOURCE, client.settings.get_str('api_base'))
        self.assertLoggedTrue('streaming required', client.settings.get_bool('require_streaming'))
        self.assertLoggedTrue('partial updates enabled', client.enable_streaming)

    def test_client_gets_refreshed_token(self) -> None:
        """A token without enough time left is refreshed before the client is created."""
        auth = FakeChatGPTAuth(SignedInStore(expires_in=600.0), responses=[{'access_token': 'access-2', 'expires_in': 3600}])
        provider = self._create_provider(auth)

        client = provider.GetTranslationClient(SettingsType({'instructions': 'Translate.'}))

        self.assertLoggedEqual('api key', 'access-2', client.settings.get_str('api_key'))

    @skip_if_debugger_attached
    def test_unidentified_app_cannot_use_plan(self) -> None:
        """Without an application name the plan is not used, rather than falling back to another app's sign-in."""
        with patch.object(chatgpt_auth_module, '_app_name', None):
            provider = OpenAiProvider(SettingsType({'use_chatgpt_plan': True, 'model': 'gpt-plan'}))

            options = provider.GetOptions(provider.settings)
            self.assertLoggedEqual('account option', ChatGPTSignInOption, options['chatgpt_account'][0])
            self.assertLoggedFalse('settings valid', provider.ValidateSettings())

            with self.assertRaises(ProviderError) as context:
                provider.GetTranslationClient(SettingsType({'instructions': 'Translate.'}))
            log_input_expected_error('no application name', ProviderError, context.exception)

    def test_api_key_mode_is_unchanged(self) -> None:
        provider = OpenAiProvider(SettingsType({'api_key': 'sk-test', 'use_chatgpt_plan': False}))

        options = provider.GetOptions(provider.settings)

        self.assertLoggedIn('api key option', 'api_key', options)
        self.assertLoggedNotIn('account option', 'chatgpt_account', options)


@unittest.skipUnless(_openai_available, "openai package is not installed")
class OpenAIReasoningClientPlanUsageTests(LoggedTestCase):
    """Tests for the request settings that ChatGPT plan usage relies on."""

    def _create_client(self, events : list[Any], **settings : Any) -> tuple[OpenAIReasoningClient, FakeOpenAI]:
        client = OpenAIReasoningClient(SettingsType({
            'api_key': 'access-1',
            'instructions': 'Translate.',
            'model': 'gpt-plan',
            **settings,
        }))
        fake = FakeOpenAI(events)
        client.client = cast(Any, fake)
        return client, fake

    def test_required_streaming_without_callback(self) -> None:
        """Requests are streamed and not stored even without a streaming callback."""
        completed = ResponseCompletedEvent.model_construct(type='response.completed', sequence_number=1, response=MakeCompletedResponse())
        client, fake = self._create_client([completed], require_streaming=True, store_responses=False)

        response = client._get_client_response(MakeRequest())

        self.assertLoggedIsNotNone('response', response)
        self.assertLoggedTrue('streamed', fake.responses.kwargs.get('stream') is True)
        self.assertLoggedTrue('not stored', fake.responses.kwargs.get('store') is False)

    def test_default_request_is_not_streamed(self) -> None:
        client, fake = self._create_client([])

        client._get_client_response(MakeRequest())

        self.assertLoggedNotIn('stream argument', 'stream', fake.responses.kwargs)

    @skip_if_debugger_attached
    def test_usage_limit_stops_translation(self) -> None:
        """Reaching the plan usage limit cannot be fixed by retrying."""
        failed_response = MakeCompletedResponse()
        failed_response.error = ResponseError.model_construct(code=USAGE_LIMIT_EXCEEDED, message='Usage limit reached')
        failed = ResponseFailedEvent.model_construct(type='response.failed', sequence_number=1, response=failed_response)
        client, _fake = self._create_client([failed], require_streaming=True)

        with self.assertRaises(TranslationImpossibleError) as context:
            client._get_client_response(MakeRequest())
        log_input_expected_error(USAGE_LIMIT_EXCEEDED, TranslationImpossibleError, context.exception)


if __name__ == '__main__':
    unittest.main()
