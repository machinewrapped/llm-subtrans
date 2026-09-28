from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Parse import ParseDelayFromHeader
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult


class TranscriptionClient:
    """
    Base client for provider-specific speech-to-text backends.

    A client transcribes one in-memory audio chunk at a time. Subclasses
    implement ``_transcribe_chunk`` and convert their backend's response into
    a ``TranscriptionResult`` containing text plus any available metadata,
    such as word timings, sub-segments, speaker labels, detected language,
    duration, or usage cost. The ``supports_timestamps`` and
    ``supports_diarization`` properties advertise the capabilities needed by
    the transcription coordinator.

    The base class centralizes behavior shared by remote and local clients:
    language hints, request timeouts, optional request-rate throttling,
    abort signaling, and common HTTP POST/JSON validation with bounded
    rate-limit retries. Provider-specific clients remain responsible for
    authentication, request formats, model loading, and response parsing.
    """
    _MAX_RETRIES : int = 3
    _BACKOFF_BASE : float = 5.0
    _GIVE_UP_SECONDS : float = 300.0

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

    @property
    def language(self) -> str|None:
        """Spoken language hint resolved by the provider, or None to auto-detect."""
        return self.settings.get_str('language') or None

    @property
    def proxy_url(self) -> str|None:
        """Proxy to route HTTP requests through, or None when unset."""
        return self.settings.get_str_or_none('proxy')

    def TranscribeChunk(self, audio_bytes : bytes, audio_format : str) -> TranscriptionResult:
        """
        Transcribe a single audio chunk and return its text.
        """
        if self.aborted:
            raise SubtitleError(_("Transcription aborted"))

        if not audio_bytes:
            raise SubtitleError(_("No audio data provided for transcription"))

        start_time = time.monotonic()
        result = self._transcribe_chunk(audio_bytes, audio_format)

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

    def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str) -> TranscriptionResult:
        """
        Make the backend request using self.language as the hint. Must be implemented by subclasses.
        """
        raise NotImplementedError

    def _sleep_abortable(self, seconds : float) -> None:
        """Wait out a rate-limit backoff, still honouring aborts."""
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            if self.aborted:
                raise SubtitleError(_("Transcription aborted"))
            time.sleep(min(0.5, deadline - time.monotonic()))

    def _PostRequestWithRetry(self, url : str, *, headers : dict|None = None,
                              json_body : dict|None = None,
                              files : dict|None = None) -> httpx.Response:
        """
        POST with automatic retry on HTTP 429 (rate-limited).

        Retries up to ``_MAX_RETRIES`` times with delays computed by
        ``_RetryDelayFromResponse``, which subclasses can override to
        parse provider-specific headers.  Returns the final response
        (success or the last 429 if retries are exhausted).
        """
        response = self._PostRequest(url, headers=headers, json_body=json_body, files=files)

        for attempt in range(self._MAX_RETRIES):
            if response.status_code != 429:
                return response

            delay = self._RetryDelayFromResponse(response, attempt)
            if delay is None:
                return response

            logging.warning(_("Rate limited (attempt {}/{}), retrying in {:.0f}s...").format(
                attempt + 1, self._MAX_RETRIES + 1, delay))
            self._sleep_abortable(delay)

            response = self._PostRequest(url, headers=headers, json_body=json_body, files=files)

        return response

    def _RetryDelayFromResponse(self, response : httpx.Response, attempt : int) -> float|None:
        """
        Compute a retry delay from a 429 response, or None to give up.

        Checks ``Retry-After`` and ``x-ratelimit-reset-requests`` headers,
        falling back to exponential backoff.  Returns None when the server
        requests a delay longer than ``_GIVE_UP_SECONDS`` (a quota-level
        block rather than a transient burst limit).

        Subclasses may override this to parse additional provider-specific
        rate-limit headers.
        """
        retry_after = (response.headers.get('retry-after')
                       or response.headers.get('x-ratelimit-reset-requests'))

        if retry_after:
            delay = ParseDelayFromHeader(retry_after)
            if delay > self._GIVE_UP_SECONDS:
                return None
            return max(1.0, delay)

        return self._BACKOFF_BASE * 2.0 ** attempt

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
        response = self._PostRequestWithRetry(url, headers=headers, json_body=json_body, files=files)
        return self._ParseJsonResponse(url, response)

    def _PostRequest(self, url : str, *, headers : dict|None = None,
                     json_body : dict|None = None, files : dict|None = None) -> httpx.Response:
        """
        Execute the HTTP POST, wrapping connection errors in SubtitleError.

        Returns the raw httpx.Response for callers that need to inspect it
        before JSON parsing (e.g. provider-specific status-code checks).
        """
        # Sanctioned lazy import: the startup profile attributed about 1.25 seconds to loading httpx through the transcription client.
        import httpx

        proxy = self.proxy_url
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
