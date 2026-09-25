"""
Diagnostic capture of raw transcription output.

Captures the segments a provider returns, before the line builder touches
them, so a real transcription can be replayed offline against different
code or settings (see scripts/replay_transcription.py).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, fields
from datetime import timedelta
from typing import Any

from PySubtrans.SettingsType import SettingsType
from PySubtrans.Transcription.LineSettings import LineSettings
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionSegment
from PySubtrans.Transcription.WordAlignment import WordCoverage
from PySubtrans.Transcription.WordTiming import WordTiming

# Set either to capture the next transcription
CAPTURE_PATH_ENV = 'TRANSCRIPTION_CAPTURE_PATH'
CAPTURE_PATH_SETTING = 'transcription_capture_path'


def CapturePath(settings : SettingsType|None = None) -> str|None:
    """The file to capture to, or None when capture is not requested."""
    path = settings.get_str(CAPTURE_PATH_SETTING) if settings is not None else None
    path = path or os.getenv(CAPTURE_PATH_ENV)
    return path.strip() or None if path else None


class TranscriptionCapture:
    """
    Accumulates raw provider segments and writes them as JSON.

    The file is rewritten after every segment so an aborted run still
    leaves a readable capture.
    The line settings the run assembled lines with are recorded too, so a replay can reproduce them.
    """
    def __init__(self, path : str, provider : str, media_path : str|None = None, line_settings : LineSettings|None = None):
        self.path : str = path
        self.provider : str = provider
        self.media_path : str|None = media_path
        self.line_settings : LineSettings|None = line_settings
        self.segments : list[TranscriptionSegment] = []

    def Add(self, segment : TranscriptionSegment) -> None:
        """Record a segment and rewrite the capture file."""
        self.segments.append(segment)

        try:
            with open(self.path, 'w', encoding='utf-8') as file:
                json.dump(self._document(), file, ensure_ascii=False, indent=2)

        except OSError as e:
            logging.error(f"Unable to write transcription capture: {e}")

    def _document(self) -> dict[str, Any]:
        document : dict[str, Any] = {
            'provider': self.provider,
            'media': os.path.basename(self.media_path) if self.media_path else None,
        }

        if self.line_settings is not None:
            document['line_settings'] = SerializeLineSettings(self.line_settings)

        document['segments'] = [SerializeSegment(segment) for segment in self.segments]
        return document


def SerializeLineSettings(settings : LineSettings) -> dict[str, Any]:
    """Line settings as plain JSON-safe data."""
    data = asdict(settings)
    data['word_coverage'] = settings.word_coverage.value
    return data


def DeserializeLineSettings(data : dict[str, Any]) -> LineSettings|None:
    """Rebuild line settings from captured data, or None if a field is missing."""
    names = {field.name for field in fields(LineSettings)}
    if not names.issubset(data):
        return None

    values = {name: data[name] for name in names}
    values['word_coverage'] = WordCoverage(values['word_coverage'])
    return LineSettings(**values)


def SerializeSegment(segment : TranscriptionSegment) -> dict[str, Any]:
    """A segment as plain JSON-safe data, with timings in seconds."""
    data : dict[str, Any] = {
        'start': segment.start.total_seconds(),
        'end': segment.end.total_seconds(),
        'text': segment.text,
    }

    if segment.speaker is not None:
        data['speaker'] = segment.speaker
    if segment.language is not None:
        data['language'] = segment.language
    if segment.confidence is not None:
        data['confidence'] = segment.confidence
    if segment.words:
        data['words'] = [{'text': word.text,
                          'start': word.start.total_seconds(),
                          'end': word.end.total_seconds(),
                          'speaker': word.speaker} for word in segment.words]
    if segment.parts:
        data['parts'] = [SerializeSegment(part) for part in segment.parts]

    return data


def DeserializeSegment(data : dict[str, Any]) -> TranscriptionSegment:
    """Rebuild a segment from captured data."""
    return TranscriptionSegment(
        start=timedelta(seconds=float(data.get('start', 0.0))),
        end=timedelta(seconds=float(data.get('end', 0.0))),
        text=str(data.get('text', '')),
        speaker=data.get('speaker'),
        language=data.get('language'),
        confidence=data.get('confidence'),
        words=[WordTiming(text=str(word.get('text', '')),
                          start=timedelta(seconds=float(word.get('start', 0.0))),
                          end=timedelta(seconds=float(word.get('end', 0.0))),
                          speaker=word.get('speaker')) for word in data.get('words', [])],
        parts=[DeserializeSegment(part) for part in data.get('parts', [])])


def LoadCaptureProvider(path : str) -> str|None:
    """The name of the provider a capture was taken from, if it was recorded."""
    with open(path, 'r', encoding='utf-8') as file:
        document = json.load(file)

    provider = document.get('provider')
    return str(provider) if provider else None


def LoadCaptureLineSettings(path : str) -> LineSettings|None:
    """The line settings a capture's run assembled lines with, if they were recorded."""
    with open(path, 'r', encoding='utf-8') as file:
        document = json.load(file)

    data = document.get('line_settings')
    return DeserializeLineSettings(data) if isinstance(data, dict) else None


def LoadCapture(path : str) -> list[TranscriptionSegment]:
    """Read a captured transcription back as provider segments."""
    with open(path, 'r', encoding='utf-8') as file:
        document = json.load(file)

    return [DeserializeSegment(segment) for segment in document.get('segments', [])]
