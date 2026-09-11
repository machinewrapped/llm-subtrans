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
    Words, when present, carry chunk-relative timings from a word-level
    engine (local ASR with timestamps or a forced aligner).
    Parts, when present, are chunk-relative sub-segments (e.g. provider
    segments without word timings) promoted to lines by the coordinator.
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
    The transcribed text for one audio chunk, with optional metadata.

    Words carry chunk-relative timings when the engine returns them.
    Parts carry chunk-relative sub-segments (text with start/end) for
    engines that return segments but no word timings. Both are empty
    for flat-text engines. Cost is the billed amount in USD when the
    backend reports usage (OpenRouter does per request).
    """
    text : str = ""
    language : str|None = None
    duration : timedelta|None = None
    words : list[WordTiming] = field(default_factory=list)
    parts : list[TranscriptionSegment] = field(default_factory=list)
    cost : float|None = None
