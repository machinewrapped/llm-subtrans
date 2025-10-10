import logging
import json
from typing import Any, Literal, cast

from openai import BadRequestError
from openai.types import responses as responses_types
from openai.types.responses import (
    EasyInputMessageParam,
    ResponseInputParam,
    ResponseTextDeltaEvent,
    ResponseCompletedEvent,
    ResponseFailedEvent,
    ResponseIncompleteEvent,
)
from openai.types.completion_usage import CompletionTokensDetails
from openai.types.shared_params.reasoning import Reasoning
from openai.types.shared.reasoning_effort import ReasoningEffort

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
    def reasoning_effort(self) -> ReasoningEffort:
        effort = self.settings.get_str('reasoning_effort') or "low"
        return cast(ReasoningEffort, effort)

    @property
    def is_streaming(self) -> bool:
        return self._is_streaming

    # ----------------------------
    # Internal logging helpers
    # ----------------------------
    def _log_bad_request_details(self, e: BadRequestError, where: str) -> None:
        """
        Dump as much structured info as possible from an OpenAI BadRequestError
        so we can see the exact validation error returned by the API.
        """
        try:
            status = getattr(e, "status_code", None) or getattr(e, "status", None)
        except Exception:
            status = None

        try:
            request_id = getattr(e, "request_id", None) or getattr(e, "requestId", None)
        except Exception:
            request_id = None

        message = str(e)

        body_repr = None
        try:
            resp = getattr(e, "response", None)
            if resp is not None:
                # httpx.Response in modern SDKs
                try:
                    body_json = resp.json()
                    body_repr = json.dumps(body_json, indent=2, ensure_ascii=False)
                except Exception:
                    try:
                        body_repr = resp.text
                    except Exception:
                        body_repr = "<no response body available>"
            else:
                body_repr = "<no response attached to exception>"
        except Exception as ex:
            body_repr = f"<failed extracting error body: {ex}>"

        logging.error(
            "OpenAI BadRequest during %s: status=%s request_id=%s message=%s",
            where, status, request_id, message
        )
        # Keep big errors readable but bounded
        if body_repr is not None:
            max_len = 8000
            clipped = (body_repr[:max_len] + " …[truncated]") if len(body_repr) > max_len else body_repr
            logging.error("OpenAI BadRequest (%s) error body:\n%s", where, clipped)

    def _log_stream_event_error(self, event: ResponseFailedEvent | ResponseIncompleteEvent) -> None:
        """
        Log details from streaming failure/incomplete events.
        """
        try:
            err = getattr(event, "error", None)
            if err:
                err_type = getattr(err, "type", None)
                err_code = getattr(err, "code", None)
                err_msg = getattr(err, "message", None) or getattr(err, "error", None)
                logging.error(
                    "Streaming error event: type=%s code=%s message=%s",
                    err_type, err_code, err_msg
                )
            else:
                # Fall back to whatever we can get from the response
                resp = getattr(event, "response", None)
                stop_reason = getattr(resp, "stop_reason", None)
                finish_reason = getattr(resp, "finish_reason", None)
                logging.error(
                    "Streaming failed/incomplete without explicit error object. stop_reason=%s finish_reason=%s",
                    stop_reason, finish_reason
                )
        except Exception as ex:
            logging.error("Failed to log streaming error event details: %s", ex)

    # ----------------------------
    # Main request/response flow
    # ----------------------------
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

        try:
            if request.is_streaming:
                # Streaming: complex event loop with delta accumulation
                logging.debug("OpenAIReasoningClient: starting streaming responses.create()")
                return self._handle_streaming_response(request)

            # Convert message dicts to properly typed input parameters
            input_params = self._convert_to_input_params(prompt.content)
            logging.debug(
                "OpenAIReasoningClient: non-streaming responses.create() "
                "model=%s instructions_len=%s messages=%d",
                self.model,
                len(request.prompt.system_prompt or ""),
                len(input_params) if isinstance(input_params, list) else 1
            )

            return self.client.responses.create(
                model=self.model,
                input=input_params,
                instructions=request.prompt.system_prompt,
                reasoning=Reasoning(effort=self.reasoning_effort)
            )
        except BadRequestError as e:
            # Log the full server-provided error before re-raising as TranslationError
            self._log_bad_request_details(e, where="non-streaming")
            error_msg = str(e)
            if 'reasoning.effort' in error_msg or 'reasoning' in error_msg.lower():
                raise TranslationError(_("Invalid reasoning configuration: {error}. Check that the reasoning effort value is valid for your model.").format(error=error_msg))
            raise TranslationError(_("Bad request to OpenAI API: {error}").format(error=error_msg))

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
        if not isinstance(request.prompt.content, list):
            raise TranslationError(_("Content must be a list for streaming Responses API"))

        # Convert message dicts to properly typed input parameters
        input_params = self._convert_to_input_params(request.prompt.content)

        logging.debug(
            "OpenAIReasoningClient: streaming responses.create() "
            "model=%s instructions_len=%s messages=%d",
            self.model,
            len(request.prompt.system_prompt or ""),
            len(input_params) if isinstance(input_params, list) else 1
        )

        try:
            stream = self.client.responses.create(
                model=self.model,
                input=input_params,
                instructions=request.prompt.system_prompt,
                reasoning=Reasoning(effort=self.reasoning_effort),
                stream=True
            )
        except BadRequestError as e:
            # If the server rejects the *initial* streaming request, we'll land here
            self._log_bad_request_details(e, where="streaming (create)")
            error_msg = str(e)
            if 'reasoning.effort' in error_msg or 'reasoning' in error_msg.lower():
                raise TranslationError(_("Invalid reasoning configuration: {error}. Check that the reasoning effort value is valid for your model.").format(error=error_msg))
            raise TranslationError(_("Bad request to OpenAI API: {error}").format(error=error_msg))

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
                    # Log any error metadata provided in the event
                    self._log_stream_event_error(event)
                    return event.response

        except BadRequestError as e:
            # Some SDKs may raise during iteration on protocol errors
            self._log_bad_request_details(e, where="streaming (iterate)")
            error_msg = str(e)
            if 'reasoning.effort' in error_msg or 'reasoning' in error_msg.lower():
                raise TranslationError(_("Invalid reasoning configuration: {error}. Check that the reasoning effort value is valid for your model.").format(error=error_msg))
            raise TranslationError(_("Bad request to OpenAI API: {error}").format(error=error_msg))

        except Exception as e:
            logging.warning(f"Error during streaming: {e}")

        finally:
            self._is_streaming = False

        # If we get here without a completion event, something went wrong
        raise TranslationResponseError(_("Streaming did not complete successfully"), response=None)

    def _convert_to_input_params(self, content: str|list[str]|list[dict[str, str]]) -> ResponseInputParam:
        """
        Convert message content to properly typed ResponseInputParam
        """
        if not isinstance(content, list):
            raise TranslationError(_("Content must be a list for Responses API"))

        # Content should always be a list of dictionaries for this client
        if content and isinstance(content[0], str):
            raise TranslationError(_("Content must be a list of message dicts for Responses API"))

        input_params : list[EasyInputMessageParam] = []

        for msg in content:
            if not isinstance(msg, dict):
                raise TranslationError(_("Content must be a list of message dicts for Responses API. Found item of type {type}.").format(type=type(msg).__name__))

            role = msg.get('role', 'user')
            msg_content = msg.get('content', '')

            # Validate role is one of the accepted values
            if role not in ('user', 'system', 'developer', 'assistant'):
                raise TranslationError(_("Invalid message role: {role}. Must be one of 'user', 'system', 'developer', or 'assistant'.").format(role=role))

            # EasyInputMessageParam requires role to be a specific literal type
            typed_role = cast(Literal['user', 'system', 'developer', 'assistant'], role)

            input_params.append(EasyInputMessageParam(
                content=msg_content,
                role=typed_role,
                type='message'
            ))

        # ResponseInputParam is a List union type, so we cast our list to match
        return cast(ResponseInputParam, input_params)
