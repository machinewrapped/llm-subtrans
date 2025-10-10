from __future__ import annotations

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import log_input_expected_error, skip_if_debugger_attached
from PySubtrans.Providers.Clients.OpenAIReasoningClient import OpenAIReasoningClient
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import TranslationError


class OpenAIReasoningClientTests(LoggedTestCase):
    """Tests validating the Responses API payload conversion for the reasoning client."""

    def setUp(self) -> None:
        super().setUp()
        settings = SettingsType({
            'api_key': 'sk-test',
            'instructions': 'Verify input conversion.',
            'model': 'gpt-5-mini'
        })
        self.client = OpenAIReasoningClient(settings)
        self.valid_messages = [
            {'role': 'user', 'content': 'Translate Hello to French.'}
        ]

    def test_convert_to_input_params_with_valid_messages(self) -> None:
        """Ensure valid messages convert into EasyInputMessageParam entries."""
        result = self.client._convert_to_input_params(self.valid_messages)
        self.assertLoggedEqual('converted message count', 1, len(result))
        message = result[0]
        self.assertLoggedEqual('message role', 'user', message.get('role'))
        self.assertLoggedEqual('message content', 'Translate Hello to French.', message.get('content'))
        self.assertLoggedEqual('message type', 'message', message.get('type'))

    @skip_if_debugger_attached
    def test_convert_to_input_params_rejects_non_list(self) -> None:
        """Reject content that is not expressed as a list."""
        with self.assertRaises(TranslationError) as context:
            self.client._convert_to_input_params('invalid')  # type: ignore[arg-type]
        log_input_expected_error('invalid', TranslationError, context.exception)

    @skip_if_debugger_attached
    def test_convert_to_input_params_rejects_invalid_role(self) -> None:
        """Reject message entries that use unsupported roles."""
        invalid_messages = [
            {'role': 'narrator', 'content': 'Hello'}
        ]
        with self.assertRaises(TranslationError) as context:
            self.client._convert_to_input_params(invalid_messages)
        log_input_expected_error(invalid_messages, TranslationError, context.exception)
