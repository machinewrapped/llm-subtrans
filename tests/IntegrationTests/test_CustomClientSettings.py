"""Blank settings must mean unset - httpx rejects an empty proxy URL with an obscure error."""
from typing import Any
from unittest.mock import MagicMock, patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import skip_if_debugger_attached
from PySubtrans.Providers.Clients.CustomClient import CustomClient
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import TranslationImpossibleError
from tests.IntegrationTests.test_CustomClient import (
    _create_test_request,
    _create_test_settings,
    _mock_response,
)


class TestCustomClientBlankSettings(LoggedTestCase):
    """Blank settings must read as unset - httpx rejects an empty proxy URL with an obscure error."""

    def _successful_body(self) -> str:
        return '{"choices": [{"message": {"role": "assistant", "content": "Hello"}}]}'

    def _post_with_settings(self, settings : SettingsType) -> dict[str, Any]:
        """Make one non-streaming request and return the kwargs httpx.Client was constructed with."""
        client = CustomClient(settings)
        mock_httpx_client = MagicMock()
        mock_httpx_client.post.return_value = _mock_response(200, self._successful_body())

        with patch('httpx.Client', return_value=mock_httpx_client) as mock_client_class:
            client._make_request(_create_test_request(), temperature=0.0)

        return dict(mock_client_class.call_args.kwargs)

    def test_blank_proxy_is_not_passed_to_httpx(self) -> None:
        """An empty proxy setting means no proxy, not a proxy with an empty URL."""
        test_cases = ["", "   "]

        for proxy in test_cases:
            with self.subTest(proxy=proxy):
                settings = _create_test_settings()
                settings['proxy'] = proxy

                kwargs = self._post_with_settings(settings)

                self.assertLoggedIsNone("no proxy passed to httpx", kwargs.get('proxy'), input_value=proxy)

    def test_configured_proxy_is_passed_to_httpx(self) -> None:
        """A configured proxy still reaches httpx."""
        settings = _create_test_settings()
        settings['proxy'] = 'http://localhost:8080'

        kwargs = self._post_with_settings(settings)

        self.assertLoggedEqual("proxy passed through", 'http://localhost:8080', kwargs.get('proxy'))

    @skip_if_debugger_attached
    def test_blank_server_address_is_reported_as_a_configuration_error(self) -> None:
        """A blank server address is reported as a configuration error, not an httpx failure."""
        settings = _create_test_settings()
        settings['server_address'] = ''

        client = CustomClient(settings)

        with patch('httpx.Client') as mock_client_class:
            with self.assertRaises(TranslationImpossibleError):
                client._make_request(_create_test_request(), temperature=0.0)

        self.assertLoggedFalse("httpx not invoked", mock_client_class.called)
