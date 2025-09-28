import logging

from openai.types import responses as responses_types
from openai.types.responses import (
    ResponseStreamEvent,
    ResponseTextDeltaEvent,
    ResponseCompletedEvent,
    ResponseFailedEvent,
    ResponseIncompleteEvent,
    ResponseUsage
)
from openai.types.completion_usage import CompletionTokensDetails

from typing import Any
from PySubtrans.Helpers.Localization import _
from PySubtrans.Providers.Clients.OpenAIClient import OpenAIClient
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import TranslationError, TranslationResponseError
from PySubtrans.TranslationPrompt import TranslationPrompt
from PySubtrans.TranslationRequest import TranslationRequest

linesep = '\n'

class OpenAIReasoningClient(OpenAIClient):
    """
    Handles chat communication with OpenAI to request translations using the Responses API
    """
    def __init__(self, settings: SettingsType):
        settings.update({
            'supports_system_messages': True,
            'supports_conversation': True,
            'supports_reasoning': True,
            'supports_system_prompt': True,
            'supports_streaming': True,
            'system_role': 'developer'
        })
        super().__init__(settings)
        self._is_streaming = False

    @property
    def reasoning_effort(self) -> str:
        return self.settings.get_str( 'reasoning_effort') or "low"

    @property
    def is_streaming(self) -> bool:
        return self._is_streaming
    
    def _send_messages(self, request: TranslationRequest, temperature: float|None) -> dict[str, Any] | None:
        """
        Make a request to OpenAI Responses API for translation
        """
        if not self.client:
            raise TranslationError(_("Client is not initialized"))

        if not self.model:
            raise TranslationError(_("No model specified"))

        openai_response = self._get_client_response(request)
        
        if self.aborted or not openai_response:
            return None
        
        # Build response with usage info and content
        response = self._extract_usage_info(openai_response)
        text, reasoning = self._extract_text_content(openai_response)
        
        response.update({
            'text': text,
            'finish_reason': self._normalize_finish_reason(openai_response)
        })
        
        if reasoning:
            response['reasoning'] = reasoning
            
        return response
            
    def _get_client_response(self, request: TranslationRequest):
        """
        Handle both streaming and non-streaming API calls
        """
        assert self.client is not None
        assert self.model is not None
        prompt : TranslationPrompt = request.prompt

        if not prompt or not prompt.content or not isinstance(prompt.content, list):
            raise TranslationError(_("No content provided for translation"))

        if request.is_streaming:
            # Streaming: complex event loop with delta accumulation
            return self._handle_streaming_response(request)

        return self.client.responses.create(
            model=self.model,
            input=prompt.content, # type: ignore[arg-type]
            instructions=request.prompt.system_prompt,
            reasoning={"effort": self.reasoning_effort} #type: ignore[arg-type]
        )

    def _extract_text_content(self, openai_response : responses_types.Response):
        """Extract text content from OpenAI Responses API structure"""
        # Standard response structure: response.output[0].content[0].text
        output = getattr(openai_response, 'output', None)
        if output and len(output) > 0:
            text_parts : list[str] = []
            reasoning_parts : list[str] = []

            for output_item in openai_response.output:
                content = getattr(output_item, 'content', None)
                if not content:
                    continue

                for content_item in content:
                    text_value = getattr(content_item, 'text', None)
                    if text_value:
                        text_parts.append(text_value)

                    reasoning_value = getattr(content_item, 'reasoning', None)
                    if not reasoning_value:
                        continue

                    if isinstance(reasoning_value, list):
                        for reasoning_part in reasoning_value:
                            if isinstance(reasoning_part, str):
                                reasoning_parts.append(reasoning_part)
                            elif hasattr(reasoning_part, 'text') and getattr(reasoning_part, 'text'):
                                reasoning_parts.append(getattr(reasoning_part, 'text'))
                            else:
                                reasoning_parts.append(str(reasoning_part))
                    elif isinstance(reasoning_value, str):
                        reasoning_parts.append(reasoning_value)
                    else:
                        reasoning_parts.append(str(reasoning_value))

            if text_parts:
                text = linesep.join(text_parts)
                reasoning = linesep.join(reasoning_parts) if reasoning_parts else None
                return text, reasoning

        raise TranslationResponseError(_("No text content found in response"), response=openai_response)


    def _extract_usage_info(self, openai_response : responses_types.Response) -> dict[str, Any]:
        """Extract token usage information with proper type safety"""
        usage = openai_response.usage
        if not usage:
            return {'response_time': getattr(openai_response, 'response_ms', 0)}

        info = {
            'prompt_tokens': usage.input_tokens,
            'output_tokens': usage.output_tokens,
            'total_tokens': usage.total_tokens,
            'response_time': getattr(openai_response, 'response_ms', 0)
        }

        # Add reasoning-specific tokens from output details
        if hasattr(usage, 'output_tokens_details') and usage.output_tokens_details:
            details = usage.output_tokens_details
            if hasattr(details, 'reasoning_tokens'):
                info['reasoning_tokens'] = details.reasoning_tokens

        # Handle legacy completion token details for backward compatibility
        legacy_details = getattr(usage, 'completion_tokens_details', None)
        if isinstance(legacy_details, CompletionTokensDetails):
            if legacy_details.reasoning_tokens is not None:
                info['reasoning_tokens'] = legacy_details.reasoning_tokens
            if legacy_details.accepted_prediction_tokens is not None:
                info['accepted_prediction_tokens'] = legacy_details.accepted_prediction_tokens
            if legacy_details.rejected_prediction_tokens is not None:
                info['rejected_prediction_tokens'] = legacy_details.rejected_prediction_tokens

        return {k: v for k, v in info.items() if v is not None}

    def _abort(self) -> None:
        """
        Override abort to avoid closing client socket during streaming.
        For non-streaming requests, use normal abort behavior.
        """
        if self.is_streaming:
            # Don't close the client - let the streaming loop handle it gracefully
            pass
        else:
            # Normal abort behavior for non-streaming requests
            super()._abort()

    def _normalize_finish_reason(self, result):
        """Normalize finish reason to legacy format"""
        finish = getattr(result, 'stop_reason', None) or getattr(result, 'finish_reason', None)
        return 'length' if finish == 'max_output_tokens' else finish

    def _handle_streaming_response(self, request: TranslationRequest) -> responses_types.Response|None:
        """
        Handle streaming response with delta accumulation and partial updates
        """
        assert self.client is not None
        assert self.model is not None

        stream = self.client.responses.create(
            model=self.model,
            input=request.prompt.content, # type: ignore[arg-type]
            instructions=request.prompt.system_prompt,
            reasoning={"effort": self.reasoning_effort}, #type: ignore[arg-type]
            stream=True
        )

        self._is_streaming = True
        try:
            for event in stream:
                if self.aborted:
                    return

                # Handle relevant streaming events
                if isinstance(event, ResponseTextDeltaEvent):
                    request.ProcessStreamingDelta(event.delta)

                elif isinstance(event, ResponseCompletedEvent):
                    return event.response

                elif isinstance(event, (ResponseFailedEvent, ResponseIncompleteEvent)):
                    return event.response

        except Exception as e:
            logging.warning(f"Error during streaming: {e}")

        finally:
            self._is_streaming = False

        # If we get here without a completion event, something went wrong
        raise TranslationResponseError(_("Streaming did not complete successfully"), response=None)





