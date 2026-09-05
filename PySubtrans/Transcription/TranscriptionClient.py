from __future__ import annotations

import logging

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

    def TranscribeChunk(self, audio_bytes : bytes, audio_format : str, language : str|None = None) -> TranscriptionResult:
        """
        Transcribe a single audio chunk and return its text.
        """
        if self.aborted:
            raise SubtitleError(_("Transcription aborted"))

        if not audio_bytes:
            raise SubtitleError(_("No audio data provided for transcription"))

        return self._transcribe_chunk(audio_bytes, audio_format, language)

    def AbortTranscription(self) -> None:
        """Signal that any in-flight and subsequent requests should stop."""
        self.aborted = True
        self._abort()

    def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str, language : str|None) -> TranscriptionResult:
        """
        Make the backend request. Must be implemented by subclasses.
        """
        _ = audio_bytes, audio_format, language
        raise NotImplementedError

    def _abort(self) -> None:
        """Terminate ongoing requests. Default signals the flag only."""
        self.aborted = True
        logging.debug("Transcription abort requested")
