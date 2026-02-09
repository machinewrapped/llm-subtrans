import json
from unittest.mock import MagicMock, patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import log_input_expected_error, skip_if_debugger_attached
from PySubtrans.Providers.Clients.CustomClient import CustomClient
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import (
    ClientResponseError,
    ServerResponseError,
    TranslationImpossibleError,
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
