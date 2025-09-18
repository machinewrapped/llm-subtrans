import logging
import time
from typing import Any
import httpx

from PySubtrans.Helpers import FormatMessages
from PySubtrans.Helpers.Parse import ParseErrorMessageFromText
from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import SettingsType
from PySubtrans.SubtitleError import TranslationImpossibleError, TranslationResponseError
from PySubtrans.Translation import Translation
from PySubtrans.TranslationClient import TranslationClient
from PySubtrans.TranslationPrompt import TranslationPrompt

class CustomClient(TranslationClient):
    """
    Handles communication with local LLM server to request translations
    """
    def __init__(self, settings : SettingsType):
        super().__init__(settings)
        self.client: httpx.Client|None = None
        self.headers: dict[str, str] = {'Content-Type': 'application/json'}
        self._add_additional_headers(settings)

        if self.api_key:
            self.headers['Authorization'] = f"Bearer {self.api_key}"

        logging.info(_("Translating with server at {server_address}{endpoint}").format(
            server_address=self.server_address, endpoint=self.endpoint
        ))
        if self.model:
            logging.info(_("Using model: {model}").format(model=self.model))

    @property
    def server_address(self) -> str|None:
        return self.settings.get_str( 'server_address')

    @property
    def endpoint(self) -> str|None:
        return self.settings.get_str( 'endpoint')

    @property
    def supports_conversation(self) -> bool:
        return self.settings.get_bool( 'supports_conversation', False)

    @property
    def api_key(self) -> str|None:
        return self.settings.get_str( 'api_key')

    @property
    def model(self) -> str|None:
        return self.settings.get_str( 'model')

    @property
    def max_tokens(self) -> int|None:
        max_tokens = self.settings.get_int( 'max_tokens', 0)
        return max_tokens if max_tokens != 0 else None
    
    @property
    def max_completion_tokens(self) -> int|None:
        max_completion_tokens = self.settings.get_int( 'max_completion_tokens', 0)
        return max_completion_tokens if max_completion_tokens != 0 else None
    
    @property
    def timeout(self) -> int:
        return self.settings.get_int( 'timeout') or 300

    def _request_translation(self, prompt : TranslationPrompt, temperature : float|None = None) -> Translation|None:
        """
        Request a translation based on the provided prompt
        """
        logging.debug(f"Messages:\n{FormatMessages(prompt.messages)}")

        temperature = temperature or self.temperature
        response = self._make_request(prompt, temperature)

        translation = Translation(response) if response else None

        return translation

    def _abort(self) -> None:
        if self.client:
            self.client.close()
        return super()._abort()

    def _make_request(self, prompt : TranslationPrompt, temperature: float|None) -> dict[str, Any]|None:
        """
        Make a request to the server to provide a translation
        """
        response = {}

        for retry in range(self.max_retries + 1):
            if self.aborted:
                return None

            try:
                request_body = self._generate_request_body(prompt, temperature)
                logging.debug(f"Request Body:\n{request_body}")

                if self.server_address is None or self.endpoint is None:
                    raise TranslationImpossibleError(_("Server address or endpoint is not set"))

                self.client = httpx.Client(base_url=self.server_address, follow_redirects=True, timeout=self.timeout, headers=self.headers)

                result : httpx.Response = self.client.post(self.endpoint, json=request_body)

                if self.aborted:
                    return None

                if result.is_error:
                    parsed_message = ParseErrorMessageFromText(result.text)
                    summary_text = parsed_message if parsed_message else result.text
                    if result.is_client_error:
                        raise TranslationResponseError(_("Client error: {status_code} {text}").format(
                            status_code=result.status_code, text=summary_text
                        ), response=result)
                    else:
                        raise TranslationResponseError(_("Server error: {status_code} {text}").format(
                            status_code=result.status_code, text=summary_text
                        ), response=result)

                logging.debug(f"Response:\n{result.text}")

                content = result.json()

                response['model'] = content.get('model')
                response['response_time'] = content.get('response_ms', 0)

                usage = content.get('usage', {})
                response['prompt_tokens'] = usage.get('prompt_tokens')
                response['output_tokens'] = usage.get('completion_tokens')
                response['total_tokens'] = usage.get('total_tokens')
                if 'reasoning_tokens' in usage:
                    response['reasoning_tokens'] = usage.get('reasoning_tokens')

                choices = content.get('choices')
                if not choices:
                    raise TranslationResponseError(_("No choices returned in the response"), response=result)

                for choice in choices:
                    # Try to extract translation from the response choice
                    if 'message' in choice:
                        message = choice.get('message', {})
                        response['finish_reason'] = choice.get('finish_reason')
                        if 'reasoning_content' in message:
                            response['reasoning'] = message['reasoning_content']

                        response['text'] = message.get('content')
                        break

                    if 'text' in choice:
                        response['text'] = choice.get('text')
                        response['finish_reason'] = choice.get('finish_reason')
                        break

                if not response.get('text'):
                    raise TranslationResponseError(_("No text returned in the response"), response=result)

                # Return the response if the API call succeeds
                return response

            except TranslationResponseError:
                raise

            except httpx.ConnectError as e:
                if not self.aborted:
                    logging.error(_("Failed to connect to server at {server_address}{endpoint}").format(
                        server_address=self.server_address, endpoint=self.endpoint
                    ))

            except httpx.NetworkError as e:
                if not self.aborted:
                    logging.error(_("Network error communicating with server: {error}").format(
                        error=str(e)
                    ))

            except httpx.ReadTimeout as e:
                if not self.aborted:
                    logging.error(_("Request to server timed out: {error}").format(
                        error=str(e)
                    ))

            except Exception as e:
                raise TranslationImpossibleError(_("Unexpected error communicating with server"), error=e)

            if self.aborted:
                return None
            
            if retry == self.max_retries:
                raise TranslationImpossibleError(_("Failed to communicate with server after {max_retries} retries").format(
                    max_retries=self.max_retries
                ))

            sleep_time = self.backoff_time * 2.0**retry
            logging.warning(_("Retrying in {sleep_time} seconds...").format(
                sleep_time=sleep_time
            ))
            time.sleep(sleep_time)

    def _generate_request_body(self, prompt: TranslationPrompt, temperature: float|None) -> dict[str, Any]:
        request_body = {
            'temperature': temperature,
            'stream': False
        }

        if self.max_tokens:
            request_body['max_tokens'] = self.max_tokens

        if self.max_completion_tokens:
            request_body['max_completion_tokens'] = self.max_completion_tokens

        if self.model:
            request_body['model'] = self.model

        if self.supports_conversation:
            request_body['messages'] = prompt.messages
        else:
            request_body['prompt'] = prompt.content

        return request_body

    def _add_additional_headers(self, settings):
        additional_headers = settings.get('additional_headers', {})  # Keep dict access for complex types
        if isinstance(additional_headers, dict):
            for key, value in additional_headers.items():
                if isinstance(value, str):
                    self.headers[key] = value

