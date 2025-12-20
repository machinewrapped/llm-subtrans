import json
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
from PySubtrans.TranslationRequest import TranslationRequest

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

        self._emit_info(_("Translating with server at {server_address}{endpoint}").format(
            server_address=self.server_address, endpoint=self.endpoint
        ))

        if self.proxy_url:
            self._emit_info(_("Using proxy: {proxy}").format(proxy=self.proxy_url))

        if self.model:
            self._emit_info(_("Using model: {model}").format(model=self.model))

    @property
    def server_address(self) -> str|None:
        return self.settings.get_str( 'server_address')

    @property
    def endpoint(self) -> str|None:
        return self.settings.get_str( 'endpoint')

    @property
    def proxy_url(self) -> str|None:
        return self.settings.get_str('proxy')

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

    def _request_translation(self, request: TranslationRequest, temperature: float|None = None) -> Translation|None:
        """
        Request a translation based on the provided prompt
        """
        logging.debug(f"Messages:\n{FormatMessages(request.prompt.messages)}")

        temperature = temperature or self.temperature
        response = self._make_request(request, temperature)

        translation = Translation(response) if response else None

        return translation

    def _abort(self) -> None:
        if self.client:
            self.client.close()
        return super()._abort()

    def _make_request(self, request: TranslationRequest, temperature: float|None) -> dict[str, Any]|None:
        """
        Make a request to the server to provide a translation
        """
        for retry in range(self.max_retries + 1):
            if self.aborted:
                return None

            try:
                request_body = self._generate_request_body(request, temperature)
                logging.debug(f"Request Body:\n{request_body}")

                if self.server_address is None or self.endpoint is None:
                    raise TranslationImpossibleError(_("Server address or endpoint is not set"))

                self.client = httpx.Client(
                    base_url=self.server_address,
                    follow_redirects=True,
                    timeout=self.timeout,
                    headers=self.headers,
                    proxy=self.proxy_url
                )

                # Handle streaming vs non-streaming requests
                if request.is_streaming and self.enable_streaming:
                    return self._handle_streaming_request(request, request_body)
                else:
                    return self._handle_non_streaming_request(request_body)

            except TranslationResponseError:
                raise

            except httpx.ConnectError as e:
                if not self.aborted:
                    self._emit_error(_("Failed to connect to server at {server_address}{endpoint}").format(
                        server_address=self.server_address, endpoint=self.endpoint
                    ))

            except httpx.NetworkError as e:
                if not self.aborted:
                    self._emit_error(_("Network error communicating with server: {error}").format(
                        error=str(e)
                    ))

            except httpx.ReadTimeout as e:
                if not self.aborted:
                    self._emit_error(_("Request to server timed out: {error}").format(
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
            self._emit_warning(_("Retrying in {sleep_time} seconds...").format(
                sleep_time=sleep_time
            ))
            time.sleep(sleep_time)

    def _handle_non_streaming_request(self, request_body: dict[str, Any]) -> dict[str, Any]|None:
        """Handle traditional non-streaming HTTP request"""
        assert self.client is not None
        assert self.endpoint is not None

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
        return self._process_api_response(content, result)

    def _handle_streaming_request(self, request: TranslationRequest, request_body: dict[str, Any]) -> dict[str, Any]|None:
        """Handle streaming HTTP request using Server-Sent Events"""
        assert self.client is not None
        assert self.endpoint is not None

        # Enable streaming in request body
        request_body['stream'] = True

        with self.client.stream('POST', self.endpoint, json=request_body) as response:
            if self.aborted:
                return None

            if response.is_error:
                error_text = response.text
                parsed_message = ParseErrorMessageFromText(error_text)
                summary_text = parsed_message if parsed_message else error_text
                if response.is_client_error:
                    raise TranslationResponseError(_("Client error: {status_code} {text}").format(
                        status_code=response.status_code, text=summary_text
                    ), response=response)
                else:
                    raise TranslationResponseError(_("Server error: {status_code} {text}").format(
                        status_code=response.status_code, text=summary_text
                    ), response=response)

            # Process streaming chunks
            accumulated_response = {}
            chunks_processed = 0

            try:
                for line in response.iter_lines():
                    if self.aborted:
                        return None

                    chunk_data = self._parse_sse_chunk(line)
                    if chunk_data:
                        chunks_processed += 1

                        # Handle error chunks
                        if chunk_data.get('error'):
                            error_msg = chunk_data['error']
                            if isinstance(error_msg, dict):
                                error_msg = error_msg.get('message', str(error_msg))
                            raise TranslationResponseError(_("Streaming error: {error}").format(
                                error=error_msg
                            ), response=response)

                        # Handle termination signal
                        if chunk_data.get('done'):
                            break

                        self._process_streaming_chunk(request, chunk_data, accumulated_response)

            except (ConnectionError, httpx.ReadTimeout) as e:
                if chunks_processed == 0:
                    # No data received at all, treat as connection failure
                    raise TranslationImpossibleError(_("Failed to establish streaming connection: {error}").format(
                        error=str(e)
                    ))
                else:
                    # Some data received, try to return partial response
                    self._emit_warning(f"Streaming connection interrupted after {chunks_processed} chunks: {e}")
                    if request.accumulated_text:
                        accumulated_response['text'] = request.accumulated_text
                        accumulated_response['finish_reason'] = 'interrupted'

            # Ensure we have accumulated text as fallback
            if not accumulated_response.get('text') and request.accumulated_text:
                accumulated_response['text'] = request.accumulated_text

            return accumulated_response

    def _parse_sse_chunk(self, line: str) -> dict[str, Any]|None:
        """Parse a Server-Sent Events chunk with robust handling of OpenRouter edge cases"""
        line = line.strip()

        # Skip empty lines
        if not line:
            return None

        # Handle SSE comment lines (used by OpenRouter to prevent timeouts)
        # Comments start with ':' and should be ignored per SSE specification
        if line.startswith(':'):
            logging.debug(f"SSE comment received: {line}")
            return None

        # Handle other SSE field types (event:, id:, retry:) - skip for now
        if line.startswith(('event:', 'id:', 'retry:')):
            return None

        # Only process data lines
        if not line.startswith('data: '):
            return None

        # Extract JSON data
        data_part = line[6:]  # Remove 'data: ' prefix

        # Handle termination signal
        if data_part == '[DONE]':
            return {'done': True}

        # Handle empty data lines
        if not data_part.strip():
            return None

        try:
            return json.loads(data_part)
        except json.JSONDecodeError as e:
            # More specific logging for debugging
            self._emit_warning(f"Failed to parse SSE data chunk as JSON: {data_part[:100]}... Error: {e}")
            return None

    def _process_streaming_chunk(self, request: TranslationRequest, chunk_data: dict[str, Any], accumulated_response: dict[str, Any]) -> None:
        """Process a single streaming chunk and update accumulated response"""
        # Extract delta content
        choices = chunk_data.get('choices', [])
        if not choices:
            return

        choice = choices[0]
        delta = choice.get('delta', {})

        # Handle various delta content types
        content = delta.get('content')
        if content and isinstance(content, str):
            request.ProcessStreamingDelta(content)

        # Handle reasoning content if present (some providers include this)
        reasoning_content = delta.get('reasoning_content')
        if reasoning_content and isinstance(reasoning_content, str):
            if 'reasoning' not in accumulated_response:
                accumulated_response['reasoning'] = ''
            accumulated_response['reasoning'] += reasoning_content

        # Handle function calls or tool use (skip for now, but don't error)
        function_call = delta.get('function_call')
        tool_calls = delta.get('tool_calls')
        if function_call or tool_calls:
            logging.debug("Function/tool calls in streaming response - skipping")

        # Update accumulated response with metadata
        if 'model' in chunk_data:
            accumulated_response['model'] = chunk_data['model']

        if 'usage' in chunk_data:
            usage = chunk_data['usage']
            if isinstance(usage, dict):
                accumulated_response['prompt_tokens'] = usage.get('prompt_tokens')
                accumulated_response['output_tokens'] = usage.get('completion_tokens')
                accumulated_response['total_tokens'] = usage.get('total_tokens')
                if 'reasoning_tokens' in usage:
                    accumulated_response['reasoning_tokens'] = usage.get('reasoning_tokens')

        # Handle completion
        finish_reason = choice.get('finish_reason')
        if finish_reason:
            accumulated_response['finish_reason'] = finish_reason
            accumulated_response['text'] = request.accumulated_text

    def _process_api_response(self, content: dict[str, Any], result: httpx.Response) -> dict[str, Any]:
        """Process standard API response content"""
        response = {}

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

        return response

    def _generate_request_body(self, request: TranslationRequest, temperature: float|None) -> dict[str, Any]:
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

        prompt : TranslationPrompt = request.prompt
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

