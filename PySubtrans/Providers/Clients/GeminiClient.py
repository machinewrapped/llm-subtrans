import logging

import time
from typing import Any

from google import genai
from google.genai.types import (
    AutomaticFunctionCallingConfig,
    Candidate,
    Content,
    FinishReason,
    GenerateContentConfig,
    GenerateContentResponse,
    GenerateContentResponseUsageMetadata,
    HarmBlockThreshold,
    HarmCategory,
    HttpOptions,
    Part,
    SafetySetting,
    ThinkingConfig,
    ThinkingLevel
)

from PySubtrans.Helpers import FormatMessages
from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import SettingsType
from PySubtrans.Providers.Provider_Gemini import DEFAULT_THINKING_LEVEL
from PySubtrans.SubtitleError import TranslationImpossibleError, TranslationResponseError
from PySubtrans.Translation import Translation
from PySubtrans.TranslationClient import TranslationClient
from PySubtrans.TranslationPrompt import TranslationPrompt
from PySubtrans.TranslationRequest import TranslationRequest

# Seconds between progress messages while a streamed response is still arriving.
STREAMING_PROGRESS_INTERVAL = 60.0

class GeminiClient(TranslationClient):
    """
    Handles communication with Google Gemini to request translations
    """
    def __init__(self, settings : SettingsType):
        super().__init__(settings)

        self._emit_info(_("Translating with Gemini {model} model").format(
            model=self.model or _("default")
        ))

        self.safety_settings: list[SafetySetting] = [
            SafetySetting(category=HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=HarmBlockThreshold.BLOCK_NONE),
            SafetySetting(category=HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=HarmBlockThreshold.BLOCK_NONE),
            SafetySetting(category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=HarmBlockThreshold.BLOCK_NONE),
            SafetySetting(category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=HarmBlockThreshold.BLOCK_NONE),
            SafetySetting(category=HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY, threshold=HarmBlockThreshold.BLOCK_NONE)
        ]

        self.automatic_function_calling: AutomaticFunctionCallingConfig = AutomaticFunctionCallingConfig(disable=True, maximum_remote_calls=None)

        # Configure reasoning parameters, or leave the model to use its default level
        self.thinking_config: ThinkingConfig|None = None
        thinking_level = self._get_thinking_level(settings.get_str('thinking_level'))
        if thinking_level:
            # Gemini appends thoughts to the text if include_thoughts is true, breaking the parser
            self.thinking_config = ThinkingConfig(include_thoughts=False, thinking_level=thinking_level)

    @property
    def api_key(self) -> str|None:
        return self.settings.get_str( 'api_key')

    @property
    def model(self) -> str|None:
        return self.settings.get_str( 'model')

    @property
    def proxy_url(self) -> str|None:
        return self.settings.get_str_or_none('proxy')

    @property
    def rate_limit(self) -> float|None:
        return self.settings.get_float( 'rate_limit')

    @property
    def timeout(self) -> int:
        """Seconds allowed for a request, or 0 for no limit"""
        return self.settings.get_int('timeout', 0) or 0

    def _request_translation(self, request: TranslationRequest, temperature: float|None = None) -> Translation|None:
        """
        Request a translation based on the provided prompt.
        Temperature is ignored because Gemini rejects custom sampling parameters.
        """
        prompt: TranslationPrompt = request.prompt
        logging.debug(f"Messages:\n{FormatMessages(prompt.messages)}")

        if not isinstance(prompt.system_prompt, str):
            raise TranslationImpossibleError(_("System prompt is required"))

        if not isinstance(prompt.content, str) or not prompt.content.strip():
            raise TranslationImpossibleError(_("No content provided for translation"))

        response = self._send_messages(request)

        return Translation(response) if response else None

    def _abort(self) -> None:
        return super()._abort()

    def _send_messages(self, request: TranslationRequest) -> dict[str, Any]|None:
        """
        Make a request to the Gemini API to provide a translation
        """
        if not self.model:
            raise TranslationImpossibleError(_("No model specified"))

        for retry in range(1 + self.max_retries):
            try:
                return self._get_gemini_response(request)

            except TranslationImpossibleError:
                raise

            except Exception as e:
                if retry == self.max_retries:
                    raise TranslationImpossibleError(_("Failed to communicate with provider after {max_retries} retries").format(
                        max_retries=self.max_retries
                    ))

                if not self.aborted:
                    sleep_time = self.backoff_time * 2.0**retry
                    self._emit_warning(_("Gemini request failure {error}, retrying in {sleep_time} seconds...").format(
                        error=str(e), sleep_time=sleep_time
                    ))
                    time.sleep(sleep_time)

    def _get_gemini_response(self, request: TranslationRequest) -> dict[str, Any]|None:
        """
        Handle both streaming and non-streaming Gemini API calls
        """
        if not self.model:
            raise TranslationImpossibleError(_("No model specified"))

        prompt: TranslationPrompt = request.prompt
        if not isinstance(prompt.content, str):
            raise TranslationImpossibleError(_("Content must be a string for Gemini"))

        # Configure http options (proxy support for both sync httpx and async aiohttp)
        proxy = self.proxy_url
        client_args = None
        async_client_args = None
        if proxy:
            client_args = {'proxy': proxy}
            async_client_args = {'proxy': proxy}
            self._emit_info(_("Using proxy: {proxy}").format(proxy=proxy))

        # The SDK timeout is in milliseconds.
        # It also catches a stream that goes quiet, which the deadline below cannot see.
        sdk_timeout = self.timeout * 1000 if self.timeout else None

        http_options = HttpOptions(api_version='v1beta', client_args=client_args, async_client_args=async_client_args, timeout=sdk_timeout)

        gemini_client = genai.Client(api_key=self.api_key, http_options=http_options)
        config = GenerateContentConfig(
            candidate_count=1,
            system_instruction=prompt.system_prompt,
            safety_settings=self.safety_settings,
            thinking_config=self.thinking_config,
            automatic_function_calling=self.automatic_function_calling,
            max_output_tokens=None,
            response_modalities=[]
        )

        if not request.is_streaming or not self.enable_streaming:
            # Non-streaming: single request
            gcr = gemini_client.models.generate_content(
                model=self.model,
                contents=Part.from_text(text=prompt.content),
                config=config
            )

            return self._process_gemini_response(gcr) if not self.aborted else None

        # Streaming: process chunks and create complete response
        stream = gemini_client.models.generate_content_stream(
            model=self.model,
            contents=Part.from_text(text=prompt.content),
            config=config
        )

        # A retry after a failed stream must not append to the earlier attempt's text
        request.ResetStreaming()

        last_candidate: Candidate | None = None
        last_usage: GenerateContentResponseUsageMetadata | None = None
        first_prompt_feedback = None  # when blocked, this can be set only on the first chunk
        accumulated_thoughts = ""

        # The finish reason can arrive on a final chunk that has no content parts
        finish_reason : FinishReason|None = None

        start_time = time.monotonic()
        deadline = start_time + self.timeout if self.timeout else None
        next_progress_time = start_time + STREAMING_PROGRESS_INTERVAL
        timed_out = False

        for chunk in stream:
            if self.aborted:
                return None

            chunk_text = ""
            for candidate in chunk.candidates or []:
                if candidate.finish_reason:
                    finish_reason = candidate.finish_reason

                if candidate.content and candidate.content.parts:
                    last_candidate = candidate
                    for part in candidate.content.parts:
                        if part.text:
                            if part.thought:
                                accumulated_thoughts += part.text
                            else:
                                chunk_text += part.text

            if chunk_text:
                request.ProcessStreamingDelta(chunk_text)

            if chunk.usage_metadata:
                last_usage = chunk.usage_metadata
            if chunk.prompt_feedback and first_prompt_feedback is None:
                first_prompt_feedback = chunk.prompt_feedback

            now = time.monotonic()
            response_length = len(request.accumulated_text)

            # Stop a response that runs too long and hand on what has arrived so far
            if deadline and now >= deadline:
                self._emit_warning(_("Gemini response took longer than {seconds} seconds, stopping after {characters} characters").format(
                    seconds=self.timeout, characters=response_length
                ))
                timed_out = True
                break

            if now >= next_progress_time:
                self._emit_info(_("Still receiving Gemini response after {seconds} seconds ({characters} characters)").format(
                    seconds=int(now - start_time), characters=response_length
                ))
                next_progress_time = now + STREAMING_PROGRESS_INTERVAL

        # Nothing to salvage, so fail the batch rather than resend the request
        if timed_out and not request.accumulated_text:
            return None

        # Build a synthetic response that keeps metadata but replaces content parts with accumulated text
        parts = [Part.from_text(text = request.accumulated_text)]

        if accumulated_thoughts:
            thought_part = Part.from_text(text = accumulated_thoughts)
            thought_part.thought = True
            parts.append(thought_part)

        synthetic_candidate = Candidate(
            content=Content(role="model", parts=parts),
            finish_reason = finish_reason,
            safety_ratings = getattr(last_candidate, "safety_ratings", None)
        )

        response = GenerateContentResponse(
            candidates=[synthetic_candidate],
            usage_metadata=last_usage,
            prompt_feedback=first_prompt_feedback
        )

        result = self._process_gemini_response(response)

        if timed_out:
            result['finish_reason'] = "timeout"

        return result


    def _process_gemini_response(self, gcr: GenerateContentResponse) -> dict[str, Any]:
        """
        Process Gemini response and extract translation data
        """
        response = {}

        if not gcr:
            raise TranslationImpossibleError(_("No response from Gemini"))

        if gcr.prompt_feedback and gcr.prompt_feedback.block_reason:
            block_info = self._extract_block_info(gcr)
            raise TranslationImpossibleError(_("Request was blocked by Gemini: {block_info}").format(
                block_info=block_info
            ))

        # Try to find a validate candidate
        candidates = [candidate for candidate in gcr.candidates if candidate.content] if gcr.candidates else []
        candidates = [candidate for candidate in candidates if candidate.finish_reason == FinishReason.STOP] or candidates

        if not candidates:
            raise TranslationResponseError(_("No valid candidates returned in the response"), response=gcr)

        candidate = candidates[0]
        response['token_count'] = candidate.token_count

        finish_reason = candidate.finish_reason
        if finish_reason == "STOP" or finish_reason == FinishReason.STOP:
            response['finish_reason'] = "complete"
        elif finish_reason == "MAX_TOKENS" or finish_reason == FinishReason.MAX_TOKENS:
            # Return the partial response so the translator can recover what it can.
            # Raising here would resend the identical request.
            response['finish_reason'] = "length"
            self._emit_warning(_("Gemini response exceeded token limit"))
        elif finish_reason == "SAFETY" or finish_reason == FinishReason.SAFETY:
            response['finish_reason'] = "blocked"
            raise TranslationResponseError(_("Gemini response was blocked for safety reasons"), response=candidate)
        elif finish_reason == "RECITATION" or finish_reason == FinishReason.RECITATION:
            response['finish_reason'] = "recitation"
            raise TranslationResponseError(_("Gemini response was blocked for recitation"), response=candidate)
        elif finish_reason == "FINISH_REASON_UNSPECIFIED" or finish_reason == FinishReason.FINISH_REASON_UNSPECIFIED:
            response['finish_reason'] = "unspecified"
            raise TranslationResponseError(_("Gemini response was incomplete"), response=candidate)
        else:
            # Probably a failure
            response['finish_reason'] = finish_reason

        usage_metadata : GenerateContentResponseUsageMetadata|None = gcr.usage_metadata
        if usage_metadata:
            response['prompt_tokens'] = usage_metadata.prompt_token_count
            response['output_tokens'] = usage_metadata.candidates_token_count
            response['total_tokens'] = usage_metadata.total_token_count

        if not candidate or not candidate.content or not candidate.content.parts:
            raise TranslationResponseError(_("Gemini response has no valid content parts"), response=candidate)

        response_text = "\n".join(part.text for part in candidate.content.parts if part.text)

        if not response_text:
            raise TranslationResponseError(_("Gemini response is empty"), response=candidate)

        response['text'] = response_text

        thoughts = "\n".join(part.text for part in candidate.content.parts if part.thought and part.text)
        if thoughts:
            response['reasoning'] = thoughts

        return response

    def _get_thinking_level(self, level : str|None) -> ThinkingLevel|None:
        """
        Convert a thinking level setting to the SDK value, or None to use the model default
        """
        if not level or level == DEFAULT_THINKING_LEVEL:
            return None

        thinking_level = ThinkingLevel.__members__.get(level.strip().upper())
        if thinking_level is None or thinking_level == ThinkingLevel.THINKING_LEVEL_UNSPECIFIED:
            self._emit_warning(_("Unknown Gemini thinking level {level}, using the model default").format(level=level))
            return None

        return thinking_level

    def _extract_block_info(self, gcr: GenerateContentResponse) -> str:
        """
        Extract detailed blocking information from Gemini response
        """
        info_parts = []
        has_additional_info = False
        
        if gcr.prompt_feedback and gcr.prompt_feedback.block_reason:
            block_reason = gcr.prompt_feedback.block_reason
            reason_name = getattr(block_reason, 'name', str(block_reason))
            info_parts.append(f"Reason: {reason_name}")
            
            # Add block reason message if available
            if gcr.prompt_feedback.block_reason_message:
                info_parts.append(f"Message: {gcr.prompt_feedback.block_reason_message}")
                has_additional_info = True
        
        # Add safety ratings if available
        if gcr.prompt_feedback and gcr.prompt_feedback.safety_ratings:
            safety_info = []
            for rating in gcr.prompt_feedback.safety_ratings:
                category = getattr(rating, 'category', 'Unknown')
                probability = getattr(rating, 'probability', 'Unknown')
                blocked = getattr(rating, 'blocked', False)
                
                rating_str = f"{getattr(category, 'name', str(category))}={getattr(probability, 'name', str(probability))}"
                if blocked:
                    rating_str += " (BLOCKED)"
                safety_info.append(rating_str)
            
            if safety_info:
                info_parts.append(f"Safety: {', '.join(safety_info)}")
                has_additional_info = True
        
        # If it's just PROHIBITED_CONTENT with no additional details, add explanation
        if not has_additional_info and len(info_parts) == 1 and "PROHIBITED_CONTENT" in info_parts[0]:
            info_parts.append("Google content policy violation (copyright or censorship). Try another provider.")
        
        return "; ".join(info_parts) if info_parts else "Unknown blocking reason"
