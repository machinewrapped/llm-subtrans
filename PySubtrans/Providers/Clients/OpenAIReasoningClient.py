import logging
from typing import Any
from PySubtrans.Helpers.Localization import _
from PySubtrans.Providers.Clients.OpenAIClient import OpenAIClient
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import TranslationError, TranslationResponseError
from PySubtrans.Translation import Translation
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

    @property
    def reasoning_effort(self) -> str:
        return self.settings.get_str( 'reasoning_effort') or "low"
    
    def _send_messages(self, request: TranslationRequest, temperature: float|None) -> dict[str, Any] | None:
        """
        Make a request to OpenAI Responses API for translation
        """
        if not self.client:
            raise TranslationError(_("Client is not initialized"))

        if not self.model:
            raise TranslationError(_("No model specified"))

        if not request.prompt.content or not isinstance(request.prompt.content, list):
            raise TranslationError(_("No content provided for translation"))

        result = self._get_client_response(request)
        
        if self.aborted:
            return None
        
        # Build response with usage info and content
        response = self._extract_usage_info(result)
        text, reasoning = self._extract_text_content(result)
        
        response.update({
            'text': text,
            'finish_reason': self._normalize_finish_reason(result)
        })
        
        if reasoning:
            response['reasoning'] = reasoning
            
        return response
            
    def _extract_text_content(self, result):
        """Extract text content from OpenAI Responses API structure"""
        if hasattr(result, 'output') and result.output:
            # Standard response structure: response.output[0].content[0].text
            if len(result.output) > 0:
                output_item = result.output[0]
                if hasattr(output_item, 'content') and output_item.content:
                    if len(output_item.content) > 0:
                        content_item = output_item.content[0]
                        if hasattr(content_item, 'text') and content_item.text:
                            return content_item.text, None

        raise TranslationResponseError(_("No text content found in response"), response=result)


    def _extract_usage_info(self, result):
        """Extract token usage information"""
        usage = getattr(result, 'usage', None)
        if not usage:
            return {'response_time': getattr(result, 'response_ms', 0)}
        
        info = {
            'prompt_tokens': getattr(usage, 'input_tokens', None) or getattr(usage, 'prompt_tokens', None),
            'output_tokens': getattr(usage, 'output_tokens', None) or getattr(usage, 'completion_tokens', None),
            'response_time': getattr(result, 'response_ms', 0)
        }
        
        # Calculate total if not provided
        if info['prompt_tokens'] and info['output_tokens']:
            info['total_tokens'] = info['prompt_tokens'] + info['output_tokens']
        
        # Add reasoning-specific tokens
        details = getattr(usage, 'output_tokens_details', None) or getattr(usage, 'completion_tokens_details', None)
        if details:
            reasoning_tokens = getattr(details, 'reasoning_tokens', None)
            accepted_tokens = getattr(details, 'accepted_prediction_tokens', None)
            rejected_tokens = getattr(details, 'rejected_prediction_tokens', None)
            
            if reasoning_tokens is not None:
                info['reasoning_tokens'] = reasoning_tokens
            if accepted_tokens is not None:
                info['accepted_prediction_tokens'] = accepted_tokens
            if rejected_tokens is not None:
                info['rejected_prediction_tokens'] = rejected_tokens
        
        return {k: v for k, v in info.items() if v is not None}

    def _normalize_finish_reason(self, result):
        """Normalize finish reason to legacy format"""
        finish = getattr(result, 'stop_reason', None) or getattr(result, 'finish_reason', None)
        return 'length' if finish == 'max_output_tokens' else finish

    def _get_client_response(self, request: TranslationRequest):
        """
        Handle both streaming and non-streaming API calls
        """
        if not request.is_streaming:
            # Non-streaming: simple call and return
            assert self.client is not None
            assert self.model is not None
            return self.client.responses.create(
                model=self.model,
                input=request.prompt.content,
                instructions=request.prompt.system_prompt,
                reasoning={"effort": self.reasoning_effort}
            )
        else:
            # Streaming: complex event loop with delta accumulation
            return self._handle_streaming_response(request)

    def _handle_streaming_response(self, request: TranslationRequest):
        """
        Handle streaming response with delta accumulation and partial updates
        """
        assert self.client is not None
        assert self.model is not None
        stream = self.client.responses.create(
            model=self.model,
            input=request.prompt.content,
            instructions=request.prompt.system_prompt,
            reasoning={"effort": self.reasoning_effort}, #type: ignore
            stream=True
        )

        try:
            for event in stream:
                if self.aborted:
                    break

                event_type = getattr(event, 'type', None)

                # Handle delta events for streaming updates
                if event_type == 'response.output_text.delta':
                    delta_content = getattr(event, 'delta', None)
                    if delta_content:
                        request.ProcessStreamingDelta(delta_content)

                # Handle completion - return the actual complete response
                elif event_type == 'response.completed':
                    return event.response

                # Handle failures
                elif event_type in ('response.failed', 'response.incomplete'):
                    return event.response

        except Exception as e:
            logging.warning(f"Error during streaming: {e}")

        # If we get here without a completion event, something went wrong
        return None





