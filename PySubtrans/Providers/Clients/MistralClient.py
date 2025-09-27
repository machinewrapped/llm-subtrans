import logging

from PySubtrans.Options import SettingsType
from PySubtrans.SubtitleError import TranslationResponseError

import mistralai
from mistralai.models import ChatCompletionResponse as ChatCompletion

from PySubtrans.Helpers import FormatMessages
from PySubtrans.Helpers.Localization import _
from PySubtrans.SubtitleError import TranslationError, TranslationImpossibleError
from PySubtrans.Translation import Translation
from PySubtrans.TranslationClient import TranslationClient
from PySubtrans.TranslationPrompt import TranslationPrompt
from PySubtrans.TranslationRequest import TranslationRequest

class MistralClient(TranslationClient):
    """
    Handles communication with Mistral to request translations
    """
    def __init__(self, settings : SettingsType):
        super().__init__(settings)

        if not self.api_key:
            raise TranslationImpossibleError(_("API key must be set in .env or provided as an argument"))

        logging.info(_("Translating with Mistral model {model}, using server: {server_url}").format(
            model=self.model or _("default"),
            server_url=self.server_url or _("default")
        ))

        self.client = mistralai.Mistral(api_key=self.api_key, server_url=self.server_url)

    @property
    def api_key(self) -> str|None:
        return self.settings.get_str( 'api_key')

    @property
    def server_url(self) -> str|None:
        return self.settings.get_str( 'server_url')

    @property
    def model(self) -> str|None:
        return self.settings.get_str( 'model')

    def _request_translation(self, request: TranslationRequest, temperature: float|None = None) -> Translation|None:
        """
        Request a translation based on the provided prompt
        """
        logging.debug(f"Messages:\n{FormatMessages(request.prompt.messages)}")

        content = request.prompt.content
        if not content or not isinstance(request.prompt.content, list):
            raise TranslationImpossibleError(_("No content provided for translation"))

        content = [message for message in content if message]

        temperature = temperature or self.temperature
        response = self._send_messages(content, temperature)

        translation = Translation(response) if response else None

        if translation:
            if translation.quota_reached:
                raise TranslationImpossibleError(_("Mistral account quota reached, please upgrade your plan or wait until it renews"))

            if translation.reached_token_limit:
                raise TranslationError(_("Too many tokens in translation"), translation=translation)

        return translation

    def _send_messages(self, messages : list, temperature):
        """
        Make a request to an Mistralai-compatible API to provide a translation
        """
        response = {}

        if not self.model:
            raise TranslationImpossibleError(_("No model specified"))

        if not messages:
            raise TranslationImpossibleError(_("No content provided for translation"))

        for retry in range(self.max_retries + 1): # type: ignore[unused]
            if self.aborted:
                return None

            try:
                result : ChatCompletion = self.client.chat.complete(
                    model=self.model,
                    messages=messages, # type: ignore[arg-type]
                    temperature=temperature,
                    server_url=self.server_url if self.server_url else None
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

                if hasattr(result, "usage"):
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

            except Exception as e:
                #TODO: find out what specific exceptions mistralai raises
                raise TranslationImpossibleError(_("Unexpected error communicating with the provider"), error=e)

        raise TranslationImpossibleError(_("Failed to communicate with provider after {max_retries} retries").format(
            max_retries=self.max_retries
        ))
