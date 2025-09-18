from typing import Any
from PySubtrans.Helpers.Localization import _
from PySubtrans.Providers.OpenAI.OpenAIClient import OpenAIClient
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import TranslationError, TranslationResponseError
from PySubtrans.TranslationPrompt import TranslationPrompt

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
            'system_role': 'developer'
        })
        super().__init__(settings)

    @property
    def reasoning_effort(self) -> str:
        return self.settings.get_str( 'reasoning_effort') or "low"
    
    def _send_messages(self, prompt: TranslationPrompt, temperature: float|None) -> dict[str, Any] | None:
        """
        Make a request to OpenAI Responses API for translation
        """
        if not self.client:
            raise TranslationError(_("Client is not initialized"))

        if not self.model:
            raise TranslationError(_("No model specified"))

        if not prompt.content or not isinstance(prompt.content, list):
            raise TranslationError(_("No content provided for translation"))

        result = self.client.responses.create(
            model=self.model,
            input=prompt.content, # type: ignore[arg-type]
            instructions=prompt.system_prompt,
            reasoning={"effort": self.reasoning_effort}  # type: ignore[arg-type]
        )
        
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
        """Extract text content with cleaner fallback logic"""        
        if hasattr(result, 'output') and result.output:
            return self._parse_structured_output(result.output)

        if hasattr(result, 'output_text') and result.output_text:
            return result.output_text, None

        raise TranslationResponseError(_("No text content found in response"), response=result)

    def _parse_structured_output(self, output_blocks):
        """Parse structured output blocks"""
        text_parts = []
        reasoning_parts = []
        
        for block in output_blocks:
            content = getattr(block, 'content', [])
            if content is None:
                continue

            if isinstance(content, str):
                text_parts.append(content)
                continue
                
            for item in content:
                if hasattr(item, 'text') and item.text:
                    if getattr(item, 'type', None) == 'reasoning':
                        reasoning_parts.append(item.text)
                    else:
                        text_parts.append(item.text)
                elif isinstance(item, dict):
                    if item.get('text'):
                        if item.get('type') == 'reasoning':
                            reasoning_parts.append(item['text'])
                        else:
                            text_parts.append(item['text'])

                    # Handle nested reasoning structure
                    if item.get('type') == 'reasoning':
                        r_text = (item.get('reasoning') or {}).get('text')
                        if r_text:
                            reasoning_parts.append(r_text)
        
        return ('\n'.join(text_parts) or None, 
                '\n'.join(reasoning_parts) or None)

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