import logging
import time
from typing import Any

import anthropic
import regex
from anthropic.types.message_param import MessageParam
from anthropic.types.model_param import ModelParam
from anthropic.types.thinking_config_adaptive_param import ThinkingConfigAdaptiveParam
from anthropic.types.thinking_config_enabled_param import ThinkingConfigEnabledParam
from anthropic.types.thinking_config_param import ThinkingConfigParam

from PySubtrans.Helpers import FormatMessages
from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import SettingsType
from PySubtrans.SubtitleError import TranslationError, TranslationImpossibleError
from PySubtrans.TranslationClient import TranslationClient
from PySubtrans.Translation import Translation
from PySubtrans.TranslationPrompt import TranslationPrompt
from PySubtrans.TranslationRequest import TranslationRequest

linesep = '\n'

class AnthropicClient(TranslationClient):
    """
    Handles communication with Claude via the anthropic SDK
    """
    def __init__(self, settings : SettingsType):
        super().__init__(settings)
        self.client: anthropic.Anthropic|None = None

        self._emit_info(_("Translating with Anthropic {model}").format(
            model=self.model or _("default model")
        ))

    @property
    def api_key(self) -> str|None:
        return self.settings.get_str( 'api_key')

    @property
    def model(self) -> str|None:
        return self.settings.get_str( 'model')

    @property
    def max_tokens(self) -> int:
        return self.settings.get_int( 'max_tokens') or 0
    
    @property
    def allow_thinking(self) -> bool:
        return self.settings.get_bool( 'thinking', False)
    
    @property
    def thinking(self) -> ThinkingConfigParam|anthropic.Omit:
        if self.allow_thinking:
            if not self._supports_temperature_parameter():
                return ThinkingConfigAdaptiveParam(type='adaptive')

            return ThinkingConfigEnabledParam(
                type='enabled',
                budget_tokens=self.settings.get_int('max_thinking_tokens', 1024) or 1024
            )
        
        return anthropic.omit

    def _request_translation(self, request: TranslationRequest, temperature: float|None = None) -> Translation|None:
        """
        Request a translation based on the provided prompt
        """
        try:
            self.client = anthropic.Anthropic(api_key=self.api_key)

            # Try to add proxy settings if specified
            proxy = self.settings.get_str( 'proxy')
            if proxy:
                http_client = anthropic.DefaultHttpxClient(
                    proxy = proxy
                )
                self.client = self.client.with_options(http_client=http_client)

        except Exception as e:
            raise TranslationImpossibleError(_("Failed to initialize Anthropic client"), error=e)

        prompt: TranslationPrompt = request.prompt
        logging.debug(f"Messages:\n{FormatMessages(prompt.messages)}")

        temperature = temperature or self.temperature

        if prompt.system_prompt is None:
            raise TranslationError(_("System prompt is required"))

        if not prompt.content or not isinstance(prompt.content, list):
            raise TranslationError(_("No content provided for translation"))

        if not isinstance(prompt.content, list):
            raise TranslationError(_("Content must be a list of messages"))

        response = self._send_messages(request, temperature)

        translation = Translation(response) if response else None

        if translation:
            if translation.quota_reached:
                raise TranslationImpossibleError(_("Anthropic account quota reached, please upgrade your plan or wait until it renews"))

            if translation.reached_token_limit:
                raise TranslationError(_("Too many tokens in translation"), translation=translation)

        return translation

    def _send_messages(self, request: TranslationRequest, temperature: float) -> dict[str, Any]|None:
        """
        Make a request to the LLM to provide a translation
        """
        if not self.client:
            raise TranslationImpossibleError(_("Client is not initialized"))

        api_response = self._get_client_response(request, temperature)

        if self.aborted or not api_response:
            return None

        # Process the response
        result = {}

        if api_response.stop_reason == 'max_tokens':
            result['finish_reason'] = "length"
        else:
            result['finish_reason'] = api_response.stop_reason

        if api_response.usage:
            result['prompt_tokens'] = getattr(api_response.usage, 'input_tokens')
            result['output_tokens'] = getattr(api_response.usage, 'output_tokens')

        for piece in api_response.content:
            if piece.type == 'thinking':
                result['reasoning'] = piece.thinking
            elif piece.type == 'redacted_thinking':
                result['reasoning'] = "Reasoning redacted by API"
            elif piece.type == 'text':
                result['text'] = piece.text
                break

        return result

    def _get_client_response(self, request: TranslationRequest, temperature: float):
        """
        Handle both streaming and non-streaming API calls with retry logic
        """
        if self.model is None:
            raise TranslationError(_("No model specified"))

        for retry in range(self.max_retries + 1):
            if self.aborted:
                return None

            try:
                prompt: TranslationPrompt = request.prompt
                if prompt.system_prompt is None:
                    raise TranslationError(_("System prompt is required"))

                if request.is_streaming and self.enable_streaming:
                    return self._stream_client_response(prompt, request, temperature)

                return self._create_client_response(prompt, temperature)

            except (anthropic.APITimeoutError, anthropic.RateLimitError) as e:
                if retry < self.max_retries and not self.aborted:
                    sleep_time = self.backoff_time * 2.0**retry
                    self._emit_warning(_("Anthropic API error: {error}, retrying in {sleep_time} seconds...").format(
                        error=self._get_error_message(e), sleep_time=sleep_time
                    ))
                    time.sleep(sleep_time)
                    continue

            except anthropic.APIError as e:
                raise TranslationImpossibleError(self._get_error_message(e), error=e)

            except Exception as e:
                raise TranslationError(_("Error communicating with provider"), error=e)

        raise TranslationImpossibleError(_("Failed to communicate with provider after {max_retries} retries").format(
            max_retries=self.max_retries
        ))

    def _get_error_message(self, e : anthropic.APIError) -> str:
        """ 
        Extract a user-friendly error message from the API error
        """
        if hasattr(e, 'body') and isinstance(e.body, dict):
            if 'error' in e.body and isinstance(e.body['error'], dict):
                return str(e.body['error'].get('message', str(e)))
            elif 'message' in e.body:
                return str(e.body['message'])

        return str(e)

    def _stream_client_response(self, prompt : TranslationPrompt, request : TranslationRequest, temperature : float):
        """Stream an Anthropic response with model-specific parameters."""
        if self._supports_temperature_parameter():
            with self._get_client().messages.stream(
                model=self._get_model_param(),
                thinking=self.thinking,
                messages=self._get_message_params(prompt),
                system=self._get_system_prompt(prompt),
                temperature=temperature if not self.allow_thinking else 1,
                max_tokens=self.max_tokens
            ) as stream:
                return self._consume_stream(stream, request)

        with self._get_client().messages.stream(
            model=self._get_model_param(),
            thinking=self.thinking,
            messages=self._get_message_params(prompt),
            system=self._get_system_prompt(prompt),
            max_tokens=self.max_tokens
        ) as stream:
            return self._consume_stream(stream, request)

    def _create_client_response(self, prompt : TranslationPrompt, temperature : float):
        """Create an Anthropic response with model-specific parameters."""
        if self._supports_temperature_parameter():
            return self._get_client().messages.create(
                model=self._get_model_param(),
                thinking=self.thinking,
                messages=self._get_message_params(prompt),
                system=self._get_system_prompt(prompt),
                temperature=temperature if not self.allow_thinking else 1,
                max_tokens=self.max_tokens
            )

        return self._get_client().messages.create(
            model=self._get_model_param(),
            thinking=self.thinking,
            messages=self._get_message_params(prompt),
            system=self._get_system_prompt(prompt),
            max_tokens=self.max_tokens
        )

    def _consume_stream(self, stream, request : TranslationRequest):
        """Consume streamed response content and return the final message."""
        for text in stream.text_stream:
            if self.aborted:
                return None
            request.ProcessStreamingDelta(text)

        return stream.get_final_message()

    def _get_model_param(self) -> ModelParam:
        """Return the selected model as an Anthropic model parameter."""
        if self.model is None:
            raise TranslationError(_("No model specified"))

        return self.model

    def _get_system_prompt(self, prompt : TranslationPrompt) -> str:
        """Return the system prompt in the shape expected by Anthropic."""
        if prompt.system_prompt is None:
            raise TranslationError(_("System prompt is required"))

        return prompt.system_prompt

    def _get_client(self) -> anthropic.Anthropic:
        """Return the initialized Anthropic client."""
        if self.client is None:
            raise TranslationImpossibleError(_("Client is not initialized"))

        return self.client

    def _get_message_params(self, prompt : TranslationPrompt) -> list[MessageParam]:
        """Convert prompt content into Anthropic message params."""
        if not isinstance(prompt.content, list):
            raise TranslationError(_("Content must be a list of messages"))

        messages : list[MessageParam] = []

        for message in prompt.content:
            if not isinstance(message, dict):
                raise TranslationError(_("Content must be a list of messages"))

            role = message.get('role')
            content = message.get('content')

            if role not in ('user', 'assistant') or content is None:
                raise TranslationError(_("Content must be a list of messages"))

            messages.append(MessageParam(role=role, content=content))

        return messages

    def _supports_temperature_parameter(self) -> bool:
        """Return True when the selected model still accepts the temperature parameter."""
        if self.model is None:
            return True

        match = regex.search(r'opus[-\s]+(\d+)(?:[.-](\d+))', self.model, flags=regex.IGNORECASE)
        if match is None:
            return True

        major = int(match.group(1))
        minor = int(match.group(2))

        return major < 4 or (major == 4 and minor < 7)
