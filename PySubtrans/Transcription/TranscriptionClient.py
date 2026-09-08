from __future__ import annotations

import json
import logging
import time

import httpx

from PySubtrans.Helpers.Localization import _
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult


class TranscriptionClient:
    """
    Handles communication with a transcription backend.

    v1 contract is deliberately narrow: local engines return flat text per
    chunk (no word timestamps, no diarization), so chunk boundaries provide
    the subtitle timings. Engines that return richer data can populate the
    optional fields of TranscriptionResult in future.
    """
    def __init__(self, settings : SettingsType):
        self.settings : SettingsType = SettingsType(settings)
        self.aborted : bool = False

    @property
    def supports_timestamps(self) -> bool:
        """True if the engine returns word/segment timings of its own."""
        return False

    @property
    def supports_diarization(self) -> bool:
        """True if the engine returns speaker labels."""
        return False

    @property
    def request_timeout(self) -> float:
        """Per-chunk request timeout in seconds."""
        return self.settings.get_float('request_timeout') or 300.0

    @property
    def rate_limit(self) -> float|None:
        """Maximum backend requests per minute (None or 0 for unlimited)."""
        return self.settings.get_float('rate_limit')

    def TranscribeChunk(self, audio_bytes : bytes, audio_format : str, language : str|None = None) -> TranscriptionResult:
        """
        Transcribe a single audio chunk and return its text.
        """
        if self.aborted:
            raise SubtitleError(_("Transcription aborted"))

        if not audio_bytes:
            raise SubtitleError(_("No audio data provided for transcription"))

        start_time = time.monotonic()
        result = self._transcribe_chunk(audio_bytes, audio_format, language)

        # If a rate limit is applied ensure a minimum duration for each request
        rate_limit = self.rate_limit
        if rate_limit and rate_limit > 0.0:
            minimum_duration = 60.0 / rate_limit
            elapsed_time = time.monotonic() - start_time
            if elapsed_time < minimum_duration:
                sleep_time = minimum_duration - elapsed_time
                logging.debug(f"Sleeping for {sleep_time:.2f} seconds to respect rate limit")
                self._sleep_abortable(sleep_time)

        return result

    def AbortTranscription(self) -> None:
        """Signal that any in-flight and subsequent requests should stop."""
        self.aborted = True
        self._abort()

    def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str, language : str|None) -> TranscriptionResult:
        """
        Make the backend request. Must be implemented by subclasses.
        """
        raise NotImplementedError

    def _sleep_abortable(self, seconds : float) -> None:
        """Wait out a rate-limit backoff, still honouring aborts."""
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            if self.aborted:
                raise SubtitleError(_("Transcription aborted"))
            time.sleep(min(0.5, deadline - time.monotonic()))

    def _PostJson(self, url : str, *, headers : dict|None = None,
                  json_body : dict|None = None, files : dict|None = None) -> dict:
        """
        POST to a transcription endpoint and return the parsed JSON dict.

        Handles the common pattern shared by HTTP-based transcription clients:
        open an httpx.Client with timeout and optional proxy, check for HTTP
        errors with detailed messages, reject non-JSON gateway pages, parse
        the response, and validate the payload is a dict.

        Callers supply either ``json_body`` (sent as ``json=``) or ``files``
        (sent as ``files=``), never both.
        """
        response = self._PostRequest(url, headers=headers, json_body=json_body, files=files)
        return self._ParseJsonResponse(url, response)

    def _PostRequest(self, url : str, *, headers : dict|None = None,
                     json_body : dict|None = None, files : dict|None = None) -> httpx.Response:
        """
        Execute the HTTP POST, wrapping connection errors in SubtitleError.

        Returns the raw httpx.Response for callers that need to inspect it
        before JSON parsing (e.g. provider-specific status-code checks).
        """
        proxy = self.settings.get_str('proxy')
        try:
            with httpx.Client(timeout=self.request_timeout, proxy=proxy) as client:
                if json_body is not None:
                    return client.post(url, headers=headers or {}, json=json_body)
                return client.post(url, headers=headers or {}, files=files or {})
        except Exception as e:
            raise SubtitleError(_("Transcription request failed: {}").format(str(e)), error=e)

    def _ParseJsonResponse(self, url : str, response : httpx.Response) -> dict:
        """
        Validate an HTTP response and parse its JSON body into a dict.

        Checks for HTTP errors with detailed messages, rejects non-JSON
        gateway pages, parses the JSON, and validates the payload is a dict.
        """
        if response.is_error:
            reply = (response.text or '').strip()
            if reply.startswith(('{', '[')):
                detail = reply[:500]
            elif reply:
                detail = _("non-JSON response (check the Server address): {}").format(reply[:200])
            else:
                detail = _("empty response body")
            raise SubtitleError(_("Transcription request failed: POST {} returned {}: {}").format(
                url, response.status_code, detail))

        text = (response.text or '').strip()
        if not text.startswith(('{', '[')):
            raise SubtitleError(_("Transcription failed ({}): non-JSON response: {}").format(
                response.status_code, text[:200]))

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as e:
            raise SubtitleError(_("Unable to parse transcription response"), error=e)

        if not isinstance(payload, dict):
            raise SubtitleError(_("Unexpected transcription response shape"))

        return payload

    def _abort(self) -> None:
        """Terminate ongoing requests. Default signals the flag only."""
        self.aborted = True
        logging.debug("Transcription abort requested")
