from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from PySubtrans.Transcription.WordTiming import WordTiming


@dataclass
class TranscriptionSegment:
    """
    A single transcribed span of audio.

    Timings are absolute offsets from the start of the source media.
    Speaker is None when the engine provides no diarization.
    Words, when present, carry chunk-relative timings, in the order the engine emitted them.
    Parts, when present, are the engine's own chunk-relative sub-segments, and become the lines.
    Without parts, the line builder derives them from the text, timed by the words.
    """
    start : timedelta = field(default_factory=lambda: timedelta(seconds=0))
    end : timedelta = field(default_factory=lambda: timedelta(seconds=0))
    text : str = ""
    speaker : str|None = None
    language : str|None = None
    confidence : float|None = None
    words : list[WordTiming] = field(default_factory=list)
    parts : list[TranscriptionSegment] = field(default_factory=list)


@dataclass
class TranscriptionResult:
    """
    The transcribed text for one audio chunk.

    Words and parts are chunk-relative, in the order the engine emitted them: never sort them by timing.
    Cost is the billed amount in USD, when the backend reports it.
    """
    text : str = ""
    language : str|None = None
    duration : timedelta|None = None
    words : list[WordTiming] = field(default_factory=list)
    parts : list[TranscriptionSegment] = field(default_factory=list)
    cost : float|None = None
