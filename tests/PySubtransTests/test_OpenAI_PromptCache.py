from unittest.mock import MagicMock, patch
import uuid
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from openai.types.completion_usage import CompletionUsage, PromptTokensDetails
from openai.types.responses import Response, ResponseUsage, ResponseOutputMessage, ResponseOutputText

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Options import SettingsType
from PySubtrans.Providers.Clients.ChatGPTClient import ChatGPTClient
from PySubtrans.Providers.Clients.OpenAIReasoningClient import OpenAIReasoningClient
from PySubtrans.Providers.Provider_OpenAI import OpenAiProvider
from PySubtrans.TranslationRequest import TranslationRequest
from PySubtrans.TranslationPrompt import TranslationPrompt

class TestOpenAIPromptCache(LoggedTestCase):
    def test_provider_generates_prompt_cache_key(self):
        settings = SettingsType({'api_key': 'sk-test', 'instructions': 'Test'})
        provider = OpenAiProvider(settings)

        self.assertLoggedIsNotNone("prompt_cache_key", provider.prompt_cache_key)
        assert provider.prompt_cache_key is not None
        # Check it looks like a UUID
        uuid.UUID(provider.prompt_cache_key)
        
        provider2 = OpenAiProvider(settings)
        self.assertNotEqual(provider.prompt_cache_key, provider2.prompt_cache_key, "Keys should be unique")


    @patch('PySubtrans.Providers.Clients.OpenAIClient.openai.OpenAI')
    def test_chatgpt_client_uses_prompt_cache_key(self, mock_openai):
        # Setup
        key = "test-cache-key"
        settings = SettingsType({'api_key': 'sk-test', 'model': 'gpt-4', 'prompt_cache_key': key, 'instructions': 'Test'})
        client = ChatGPTClient(settings)

        
        # Mock client creation
        mock_instance = MagicMock()
        mock_openai.return_value = mock_instance
        client._create_client()
        
        # Mock response
        mock_response = ChatCompletion.model_construct(
            id="test",
            created=123,
            model="gpt-4",
            object="chat.completion",
            choices=[Choice(finish_reason="stop", index=0, message=ChatCompletionMessage(content="Hello", role="assistant"))],
            usage=CompletionUsage.model_construct(
                prompt_tokens=20,
                completion_tokens=10,
                total_tokens=30,
                prompt_tokens_details=PromptTokensDetails.model_construct(cached_tokens=15)
            )
        )
        mock_instance.chat.completions.create.return_value = mock_response

        # Request
        prompt = TranslationPrompt("Translate")
        prompt.content = [{'role': 'user', 'content': 'Hello'}]
        request = TranslationRequest(prompt)
        response = client._send_messages(request, temperature=0.0)
        self.assertIsNotNone(response)
        assert response is not None

        
        # Verify call
        mock_instance.chat.completions.create.assert_called_once()
        kwargs = mock_instance.chat.completions.create.call_args.kwargs
        self.assertLoggedEqual("prompt_cache_key arg", key, kwargs.get('prompt_cache_key'))
        
        # Verify response extraction
        self.assertLoggedEqual("saved cached_tokens", 15, response.get('cached_tokens'))

    @patch('PySubtrans.Providers.Clients.OpenAIClient.openai.OpenAI')
    @patch('PySubtrans.Providers.Clients.OpenAIReasoningClient.SettingsType') # Patch SettingsType used in init if needed, though we pass it
    def test_reasoning_client_uses_prompt_cache_key(self, mock_settings_type, mock_openai):
        # Setup
        key = "test-reasoning-key"
        settings = SettingsType({'api_key': 'sk-test', 'model': 'o1', 'prompt_cache_key': key, 'instructions': 'Test'})
        client = OpenAIReasoningClient(settings)

        
        # Mock client creation
        mock_instance = MagicMock()
        mock_openai.return_value = mock_instance
        client._create_client()
        
        # Mock response
        mock_response = Response.model_construct(
            id="resp_test",
            created_at=123,
            model="o1",
            object="response",
            status="completed",
            output=[ResponseOutputMessage.model_construct(
                type="message", 
                role="assistant", 
                content=[ResponseOutputText.model_construct(type="output_text", text="Hello")]
            )],
            usage=ResponseUsage.model_construct(
                input_tokens=20,
                output_tokens=10,
                total_tokens=30,
                prompt_tokens_details=PromptTokensDetails.model_construct(cached_tokens=18)
            )
        )
        mock_instance.responses.create.return_value = mock_response

        # Request
        prompt = TranslationPrompt("Translate")
        prompt.content = [{'role': 'user', 'content': 'Hello'}]
        request = TranslationRequest(prompt)
        response = client._send_messages(request, temperature=None)
        self.assertIsNotNone(response)
        assert response is not None

        
        # Verify call
        mock_instance.responses.create.assert_called_once()
        kwargs = mock_instance.responses.create.call_args.kwargs
        self.assertLoggedEqual("prompt_cache_key arg", key, kwargs.get('prompt_cache_key'))
        
        # Verify response extraction
        self.assertLoggedEqual("saved cached_tokens", 18, response.get('cached_tokens'))
