import json
from unittest.mock import MagicMock, patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import log_input_expected_error, skip_if_debugger_attached
from PySubtrans.Providers.Clients.CustomClient import CustomClient
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import (
    ClientResponseError,
    TranslationImpossibleError,
    TranslationResponseError,
)
from PySubtrans.TranslationPrompt import TranslationPrompt
from PySubtrans.TranslationRequest import TranslationRequest


def _create_test_settings(streaming : bool = False) -> SettingsType:
    """Create minimal settings for CustomClient testing."""
    return SettingsType({
        'server_address': 'http://localhost:8080',
        'endpoint': '/v1/chat/completions',
        'instructions': 'Translate the subtitles.',
        'supports_conversation': True,
        'supports_streaming': streaming,
        'stream_responses': streaming,
        'max_retries': 2,
        'backoff_time': 0.01,
    })


def _create_test_request(streaming : bool = False) -> TranslationRequest:
    """Create a minimal TranslationRequest for testing."""
    prompt = TranslationPrompt("Translate this", conversation=True)
    prompt.messages = [{'role': 'user', 'content': 'Translate hello'}]
    callback = (lambda t: None) if streaming else None
    return TranslationRequest(prompt, streaming_callback=callback)


def _mock_response(status_code : int, body : str = "") -> MagicMock:
    """Create a mock httpx.Response with the given status code."""
    response = MagicMock()
    response.status_code = status_code
    response.is_error = status_code >= 400
    response.is_client_error = 400 <= status_code < 500
    response.is_server_error = 500 <= status_code < 600
    response.text = body
    try:
        response.json.return_value = json.loads(body) if body else {}
    except json.JSONDecodeError:
        response.json.return_value = {}
    return response


class TestCustomClientErrorHandling(LoggedTestCase):
    """Tests for HTTP error classification and retry behavior in CustomClient."""

    @skip_if_debugger_attached
    def test_non_streaming_4xx_raises_client_response_error(self) -> None:
        """4xx HTTP errors raise ClientResponseError."""
        client = CustomClient(_create_test_settings())
        mock_resp = _mock_response(400, '{"error": "Bad Request"}')

        mock_httpx_client = MagicMock()
        mock_httpx_client.post.return_value = mock_resp

        with patch('httpx.Client', return_value=mock_httpx_client):
            with self.assertRaises(ClientResponseError) as ctx:
                client._make_request(_create_test_request(), temperature=0.0)

        self.assertLoggedIsInstance("error type", ctx.exception, ClientResponseError)
        log_input_expected_error(400, ClientResponseError, ctx.exception)

    @skip_if_debugger_attached
    def test_non_streaming_4xx_is_not_retried(self) -> None:
        """4xx errors propagate immediately without retry."""
        client = CustomClient(_create_test_settings())
        mock_resp = _mock_response(401, "Unauthorized")

        mock_httpx_client = MagicMock()
        mock_httpx_client.post.return_value = mock_resp

        with patch('httpx.Client', return_value=mock_httpx_client):
            with self.assertRaises(ClientResponseError):
                client._make_request(_create_test_request(), temperature=0.0)

        self.assertLoggedEqual("post call count (no retry)", 1, mock_httpx_client.post.call_count)

    @skip_if_debugger_attached
    def test_non_streaming_5xx_is_retried(self) -> None:
        """5xx errors are retried up to max_retries, then raise TranslationImpossibleError."""
        client = CustomClient(_create_test_settings())
        mock_resp = _mock_response(500, '{"error": "Internal Server Error"}')

        mock_httpx_client = MagicMock()
        mock_httpx_client.post.return_value = mock_resp

        with patch('httpx.Client', return_value=mock_httpx_client):
            with self.assertRaises(TranslationImpossibleError):
                client._make_request(_create_test_request(), temperature=0.0)

        # max_retries=2 means 3 total attempts (initial + 2 retries)
        self.assertLoggedEqual("post call count (retries)", 3, mock_httpx_client.post.call_count)

    @skip_if_debugger_attached
    def test_streaming_4xx_raises_client_response_error(self) -> None:
        """Streaming 4xx errors raise ClientResponseError."""
        client = CustomClient(_create_test_settings(streaming=True))
        mock_resp = _mock_response(429, "Too Many Requests")
        mock_resp.read = MagicMock()

        mock_httpx_client = MagicMock()
        mock_httpx_client.stream.return_value.__enter__ = MagicMock(return_value=mock_resp)
        mock_httpx_client.stream.return_value.__exit__ = MagicMock(return_value=False)

        with patch('httpx.Client', return_value=mock_httpx_client):
            with self.assertRaises(ClientResponseError) as ctx:
                client._make_request(_create_test_request(streaming=True), temperature=0.0)

        self.assertLoggedIsInstance("streaming error type", ctx.exception, ClientResponseError)

    @skip_if_debugger_attached
    def test_streaming_5xx_is_retried(self) -> None:
        """Streaming 5xx errors trigger retry logic."""
        client = CustomClient(_create_test_settings(streaming=True))
        mock_resp = _mock_response(502, "Bad Gateway")
        mock_resp.read = MagicMock()

        mock_httpx_client = MagicMock()
        mock_httpx_client.stream.return_value.__enter__ = MagicMock(return_value=mock_resp)
        mock_httpx_client.stream.return_value.__exit__ = MagicMock(return_value=False)

        with patch('httpx.Client', return_value=mock_httpx_client):
            with self.assertRaises(TranslationImpossibleError):
                client._make_request(_create_test_request(streaming=True), temperature=0.0)

        # max_retries=2 means 3 total attempts
        self.assertLoggedEqual("stream call count (retries)", 3, mock_httpx_client.stream.call_count)

    @skip_if_debugger_attached
    def test_streaming_error_calls_response_read(self) -> None:
        """response.read() is called before accessing .text on streaming error responses."""
        client = CustomClient(_create_test_settings(streaming=True))
        mock_resp = _mock_response(503, "Service Unavailable")
        mock_resp.read = MagicMock()

        mock_httpx_client = MagicMock()
        mock_httpx_client.stream.return_value.__enter__ = MagicMock(return_value=mock_resp)
        mock_httpx_client.stream.return_value.__exit__ = MagicMock(return_value=False)

        with patch('httpx.Client', return_value=mock_httpx_client):
            try:
                client._make_request(_create_test_request(streaming=True), temperature=0.0)
            except TranslationImpossibleError:
                pass

        self.assertLoggedTrue("response.read() was called", mock_resp.read.called)


class TestCustomClientProcessApiResponse(LoggedTestCase):
    """Tests for _process_api_response handling of reasoning fields."""

    def _make_api_response_body(self, content : str, message_extra : dict = None) -> str:
        """Build a minimal /v1/chat/completions response body."""
        message = {'role': 'assistant', 'content': content}
        if message_extra:
            message.update(message_extra)
        return json.dumps({
            'model': 'test-model',
            'choices': [{'message': message, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30},
        })

    def test_standard_content_is_returned(self) -> None:
        """Normal responses with content are returned unchanged."""
        client = CustomClient(_create_test_settings())
        mock_resp = _mock_response(200, self._make_api_response_body('Hello world'))

        mock_httpx_client = MagicMock()
        mock_httpx_client.post.return_value = mock_resp

        with patch('httpx.Client', return_value=mock_httpx_client):
            result = client._make_request(_create_test_request(), temperature=0.0)

        self.assertLoggedEqual("text", 'Hello world', result.get('text'))
        self.assertLoggedEqual("reasoning not set", None, result.get('reasoning'))

    def test_reasoning_content_field_is_captured(self) -> None:
        """OpenAI-style reasoning_content field is captured into response['reasoning']."""
        client = CustomClient(_create_test_settings())
        body = self._make_api_response_body('The answer.', {'reasoning_content': 'I thought about it.'})
        mock_resp = _mock_response(200, body)

        mock_httpx_client = MagicMock()
        mock_httpx_client.post.return_value = mock_resp

        with patch('httpx.Client', return_value=mock_httpx_client):
            result = client._make_request(_create_test_request(), temperature=0.0)

        self.assertLoggedEqual("text", 'The answer.', result.get('text'))
        self.assertLoggedEqual("reasoning", 'I thought about it.', result.get('reasoning'))

    def test_ollama_reasoning_field_is_captured(self) -> None:
        """Ollama-style 'reasoning' field is captured into response['reasoning']."""
        client = CustomClient(_create_test_settings())
        body = self._make_api_response_body('The answer.', {'reasoning': 'I thought about it.'})
        mock_resp = _mock_response(200, body)

        mock_httpx_client = MagicMock()
        mock_httpx_client.post.return_value = mock_resp

        with patch('httpx.Client', return_value=mock_httpx_client):
            result = client._make_request(_create_test_request(), temperature=0.0)

        self.assertLoggedEqual("text", 'The answer.', result.get('text'))
        self.assertLoggedEqual("reasoning", 'I thought about it.', result.get('reasoning'))

    def test_ollama_thinking_model_empty_content_falls_back_to_reasoning(self) -> None:
        """When content is empty and reasoning is set (Ollama Qwen3), text falls back to reasoning."""
        client = CustomClient(_create_test_settings())
        body = self._make_api_response_body('', {'reasoning': 'The real translation.'})
        mock_resp = _mock_response(200, body)

        mock_httpx_client = MagicMock()
        mock_httpx_client.post.return_value = mock_resp

        with patch('httpx.Client', return_value=mock_httpx_client):
            result = client._make_request(_create_test_request(), temperature=0.0)

        self.assertLoggedEqual("text falls back to reasoning", 'The real translation.', result.get('text'))
        self.assertLoggedEqual("reasoning preserved", 'The real translation.', result.get('reasoning'))

    @skip_if_debugger_attached
    def test_empty_content_and_no_reasoning_raises_error(self) -> None:
        """Empty content with no reasoning raises TranslationResponseError."""
        client = CustomClient(_create_test_settings())
        mock_resp = _mock_response(200, self._make_api_response_body(''))

        mock_httpx_client = MagicMock()
        mock_httpx_client.post.return_value = mock_resp

        with patch('httpx.Client', return_value=mock_httpx_client):
            with self.assertRaises(TranslationResponseError) as ctx:
                client._make_request(_create_test_request(), temperature=0.0)

        self.assertLoggedIsInstance("error type", ctx.exception, TranslationResponseError)

