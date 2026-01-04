from typing import Any

from openai.types.chat import ChatCompletion    # type: ignore

from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import SettingsType
from PySubtrans.Providers.Clients.OpenAIClient import OpenAIClient
from PySubtrans.SubtitleError import TranslationError, TranslationResponseError
from PySubtrans.TranslationRequest import TranslationRequest

linesep = '\n'

class ChatGPTClient(OpenAIClient):
    """
    Handles chat communication with OpenAI to request translations
    """
    def __init__(self, settings : SettingsType):
        settings.update({
            'supports_conversation': True,
            'supports_system_messages': True
        })
        super().__init__(settings)

    def _send_messages(self, request: TranslationRequest, temperature: float|None) -> dict[str, Any]|None:
        """
        Make a request to an OpenAI-compatible API to provide a translation
        """
        response = {}

        if not self.client:
            raise TranslationError(_("Client is not initialized"))

        if not self.model:
            raise TranslationError(_("No model specified"))

        if not request.prompt.content or not isinstance(request.prompt.content, list):
            raise TranslationError(_("No content provided for translation"))

        messages: list[dict] = request.prompt.content # type: ignore[arg-type]

        assert self.client is not None
        assert self.model is not None
        result : ChatCompletion = self.client.chat.completions.create(
            model=self.model,
            messages=messages,      # type: ignore[arg-type]
            temperature=temperature,
        )

        if self.aborted:
            return None

        if not isinstance(result, ChatCompletion):
            raise TranslationResponseError(_("Unexpected response type: {response_type}").format(
                response_type=type(result).__name__
            ), response=result)

        if not getattr(result, 'choices'):
            raise TranslationResponseError(_("No choices returned in the response"), response=result)

        response['response_time'] = getattr(result, 'response_ms', 0)

        if result.usage:
            response['prompt_tokens'] = getattr(result.usage, 'prompt_tokens')
            response['output_tokens'] = getattr(result.usage, 'completion_tokens')
            response['total_tokens'] = getattr(result.usage, 'total_tokens')

        if result.choices:
            choice = result.choices[0]
            reply = result.choices[0].message

            response['finish_reason'] = getattr(choice, 'finish_reason', None)
            response['text'] = getattr(reply, 'content', None)
        else:
            raise TranslationResponseError(_("No choices returned in the response"), response=result)

        # Return the response if the API call succeeds
        return response
