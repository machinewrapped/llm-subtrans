from __future__ import annotations

from openai.types import responses as responses_types
from openai.types.responses import (
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseReasoningItem
)
from openai.types.responses.response_usage import ResponseUsage

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import log_input_expected_error, skip_if_debugger_attached
from PySubtrans.Providers.Clients.OpenAIReasoningClient import OpenAIReasoningClient
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import TranslationError, TranslationResponseError


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

    def test_convert_to_input_params_with_multiple_messages(self) -> None:
        """Ensure multiple messages with different valid roles are converted correctly."""
        messages = [
            {'role': 'user', 'content': 'First message'},
            {'role': 'assistant', 'content': 'Second message'},
            {'role': 'system', 'content': 'Third message'},
            {'role': 'developer', 'content': 'Fourth message'}
        ]
        result = self.client._convert_to_input_params(messages)
        self.assertLoggedEqual('converted message count', 4, len(result))
        self.assertLoggedSequenceEqual('message roles', ['user', 'assistant', 'system', 'developer'],
                                       [msg.get('role') for msg in result])
        self.assertLoggedSequenceEqual('message contents', ['First message', 'Second message', 'Third message', 'Fourth message'],
                                       [msg.get('content') for msg in result])

    def test_convert_to_input_params_with_empty_list(self) -> None:
        """Ensure empty message lists are handled correctly."""
        result = self.client._convert_to_input_params([])
        self.assertLoggedEqual('converted message count', 0, len(result))

    @skip_if_debugger_attached
    def test_convert_to_input_params_rejects_missing_role(self) -> None:
        """Reject message entries that are missing the role field."""
        invalid_messages = [
            {'content': 'Hello'}
        ]
        with self.assertRaises(TranslationError) as context:
            self.client._convert_to_input_params(invalid_messages)
        log_input_expected_error(invalid_messages, TranslationError, context.exception)

    @skip_if_debugger_attached
    def test_convert_to_input_params_rejects_string_list(self) -> None:
        """Reject content provided as a list of strings instead of message dicts."""
        invalid_messages = ['Hello', 'World']
        with self.assertRaises(TranslationError) as context:
            self.client._convert_to_input_params(invalid_messages)  # type: ignore[arg-type]
        log_input_expected_error(invalid_messages, TranslationError, context.exception)

    def test_extract_text_content_with_text_only(self) -> None:
        """Validate text extraction from real API response structure (reasoning item + message item)."""
        # Construct actual Response object matching real API structure
        response = responses_types.Response.model_construct(
            id="resp_test",
            created_at=1700000000.0,
            model="gpt-5-mini-test",
            object="response",
            status="completed",
            output=[
                ResponseReasoningItem.model_construct(
                    id="rs_test",
                    type="reasoning",
                    content=None,       # OpenAI does not currently return reasoning traces via the API
                    summary=[]
                ),
                ResponseOutputMessage.model_construct(
                    id="msg_test",
                    type="message",
                    role="assistant",
                    status="completed",
                    content=[
                        ResponseOutputText.model_construct(
                            type="output_text",
                            text="Bonjour."
                        )
                    ]
                )
            ],
            usage=ResponseUsage.model_construct(
                input_tokens=10,
                output_tokens=5,
                total_tokens=15
            )
        )

        text, reasoning = self.client._extract_text_content(response)
        self.assertLoggedEqual('extracted text', 'Bonjour.', text)
        self.assertLoggedIsNone('reasoning', reasoning)

    def test_extract_text_content_with_multiple_content_items(self) -> None:
        """Validate text extraction combines multiple content items with newlines."""
        response = responses_types.Response.model_construct(
            id="resp_test",
            created_at=1700000000.0,
            model="gpt-5-mini-test",
            object="response",
            status="completed",
            output=[
                ResponseReasoningItem.model_construct(
                    id="rs_test",
                    type="reasoning",
                    content=None,
                    summary=[]
                ),
                ResponseOutputMessage.model_construct(
                    id="msg_test",
                    type="message",
                    role="assistant",
                    status="completed",
                    content=[
                        ResponseOutputText.model_construct(
                            type="output_text",
                            text="First line of text."
                        ),
                        ResponseOutputText.model_construct(
                            type="output_text",
                            text="Second line of text."
                        )
                    ]
                )
            ]
        )

        text, reasoning = self.client._extract_text_content(response)
        self.assertLoggedEqual('extracted text', 'First line of text.\nSecond line of text.', text)
        self.assertLoggedIsNone('reasoning', reasoning)

    @skip_if_debugger_attached
    def test_extract_text_content_raises_on_empty_response(self) -> None:
        """Validate error is raised when response has no text content."""
        response = responses_types.Response.model_construct(
            id="resp_test",
            created_at=1700000000.0,
            model="gpt-5-mini-test",
            object="response",
            status="completed",
            output=[]
        )
        with self.assertRaises(TranslationResponseError):
            self.client._extract_text_content(response)
