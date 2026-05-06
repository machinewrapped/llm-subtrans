import importlib.util
import logging
from typing import Any

from PySubtrans.Helpers.Localization import _

if not importlib.util.find_spec("litellm"):
    logging.debug(_("LiteLLM is not installed. LiteLLM client will not be available"))
else:
    import litellm

    from PySubtrans.Helpers import FormatMessages
    from PySubtrans.Options import SettingsType
    from PySubtrans.SubtitleError import TranslationError, TranslationImpossibleError, TranslationResponseError
    from PySubtrans.Translation import Translation
    from PySubtrans.TranslationClient import TranslationClient
    from PySubtrans.TranslationRequest import TranslationRequest

    class LiteLLMClient(TranslationClient):
        """
        Handles chat communication via LiteLLM to request translations.
        Routes to 100+ LLM providers using provider-prefixed model names.
        """
        def __init__(self, settings : SettingsType):
            super().__init__(settings)

            if not self.model:
                raise TranslationImpossibleError(_("No model specified for LiteLLM"))

            self._emit_info(_("Translating with LiteLLM using model: {model}").format(
                model=self.model
            ))

        @property
        def api_key(self) -> str|None:
            return self.settings.get_str('api_key')

        @property
        def api_base(self) -> str|None:
            return self.settings.get_str('api_base')

        @property
        def model(self) -> str|None:
            return self.settings.get_str('model')

        def _request_translation(self, request : TranslationRequest, temperature : float|None = None) -> Translation|None:
            """
            Request a translation based on the provided prompt.
            """
            logging.debug(f"Messages:\n{FormatMessages(request.prompt.messages)}")

            content = request.prompt.content
            if not content or not isinstance(content, list):
                raise TranslationImpossibleError(_("No content provided for translation"))

            content = [message for message in content if message]

            temperature = temperature or self.temperature
            response = self._send_messages(content, temperature)

            translation = Translation(response) if response else None

            if translation:
                if translation.quota_reached:
                    raise TranslationImpossibleError(_("Account quota reached, please upgrade your plan or wait until it renews"))

                if translation.reached_token_limit:
                    raise TranslationError(_("Too many tokens in translation"), translation=translation)

            return translation

        def _send_messages(self, messages : list, temperature : float|None) -> dict[str, Any]|None:
            """
            Make a request to LiteLLM to provide a translation.
            """
            response : dict[str, Any] = {}

            if not self.model:
                raise TranslationImpossibleError(_("No model specified"))

            if not messages:
                raise TranslationImpossibleError(_("No content provided for translation"))

            kwargs : dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "drop_params": True,
            }
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.api_base:
                kwargs["api_base"] = self.api_base
            if temperature is not None:
                kwargs["temperature"] = temperature
            max_tokens = self.settings.get_int('max_tokens', 0)
            if max_tokens > 0:
                kwargs["max_tokens"] = max_tokens

            for retry in range(self.max_retries + 1):
                if self.aborted:
                    return None

                try:
                    result = litellm.completion(**kwargs)

                    if self.aborted:
                        return None

                    if not getattr(result, 'choices', None):
                        raise TranslationResponseError(_("No choices returned in the response"), response=result)

                    if hasattr(result, "usage") and result.usage:
                        response['prompt_tokens'] = getattr(result.usage, 'prompt_tokens', 0)
                        response['output_tokens'] = getattr(result.usage, 'completion_tokens', 0)
                        response['total_tokens'] = getattr(result.usage, 'total_tokens', 0)

                    choice = result.choices[0]
                    reply = choice.message

                    response['finish_reason'] = getattr(choice, 'finish_reason', None)
                    response['text'] = getattr(reply, 'content', None)

                    return response

                except (litellm.exceptions.RateLimitError,
                        litellm.exceptions.ServiceUnavailableError,
                        litellm.exceptions.Timeout,
                        litellm.exceptions.APIConnectionError) as e:
                    if retry < self.max_retries:
                        logging.warning(_("LiteLLM transient error (retry {retry}/{max_retries}): {error}").format(
                            retry=retry + 1, max_retries=self.max_retries, error=str(e)
                        ))
                        continue
                    raise TranslationImpossibleError(_("Failed to communicate with provider after {max_retries} retries").format(
                        max_retries=self.max_retries
                    ), error=e)

                except Exception as e:
                    raise TranslationImpossibleError(_("Unexpected error communicating with the provider"), error=e)

            raise TranslationImpossibleError(_("Failed to communicate with provider after {max_retries} retries").format(
                max_retries=self.max_retries
            ))
