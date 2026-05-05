import importlib.util
import logging

from PySubtrans.Helpers.Localization import _

if not importlib.util.find_spec("litellm"):
    logging.debug(_("LiteLLM is not installed. LiteLLM client will not be available"))
else:
    import json
    import time
    from typing import Any

    import litellm

    from PySubtrans.Options import SettingsType
    from PySubtrans.SubtitleError import TranslationImpossibleError
    from PySubtrans.Translation import Translation
    from PySubtrans.TranslationClient import TranslationClient
    from PySubtrans.TranslationPrompt import TranslationPrompt
    from PySubtrans.TranslationRequest import TranslationRequest

    class LiteLLMClient(TranslationClient):
        """
        Handles chat communication via LiteLLM to request translations.
        Routes to 100+ LLM providers using provider-prefixed model names.
        """
        def __init__(self, settings : SettingsType):
            super().__init__(settings)
            self.api_key : str|None = settings.get_str('api_key')
            self.api_base : str|None = settings.get_str('api_base')

        @property
        def model(self) -> str|None:
            return self.settings.get_str('model')

            self._emit_info(_("Translating with LiteLLM using model: {model}").format(
                model=self.model
            ))

        def _build_kwargs(self) -> dict[str, Any]:
            kwargs : dict[str, Any] = {
                "model": self.model,
                "drop_params": True,
            }
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.api_base:
                kwargs["api_base"] = self.api_base
            if self.temperature is not None:
                kwargs["temperature"] = self.temperature
            max_tokens = self.settings.get_int('max_tokens', 0)
            if max_tokens > 0:
                kwargs["max_tokens"] = max_tokens
            return kwargs

        def SendMessages(self, prompt : TranslationPrompt, temperature : float|None = None) -> TranslationRequest:
            """
            Send messages to LiteLLM and return the response.
            """
            messages = prompt.GenerateMessages()
            kwargs = self._build_kwargs()
            if temperature is not None:
                kwargs["temperature"] = temperature

            kwargs["messages"] = messages

            request = TranslationRequest(prompt)

            try:
                response = litellm.completion(**kwargs)

                content = response.choices[0].message.content or ""
                usage = getattr(response, "usage", None)
                prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
                completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

                request.prompt_tokens = prompt_tokens
                request.completion_tokens = completion_tokens
                request.response = content

                self._emit_translation_event(request, prompt)

            except Exception as e:
                request.error = str(e)
                logging.warning(_("LiteLLM error: {error}").format(error=str(e)))

            return request

        def _emit_translation_event(self, request : TranslationRequest, prompt : TranslationPrompt):
            """
            Emit translation event for logging/monitoring
            """
            pass
