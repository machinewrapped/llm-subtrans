from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from PySubtrans.SettingsType import SettingsType


@dataclass
class WordTiming:
    """
    A single aligned word (or character) with absolute media timings.
    """
    text : str = ""
    start : timedelta = field(default_factory=lambda: timedelta(seconds=0))
    end : timedelta = field(default_factory=lambda: timedelta(seconds=0))
    speaker : str|None = None


class TranscriptionAligner:
    """
    Maps transcript words onto audio time.

    Engines with native word timestamps (local ASR) populate
    TranscriptionSegment.words directly. Standalone aligner backends
    implement this interface when a validated one exists.
    """
    def __init__(self, settings : SettingsType):
        self.settings : SettingsType = SettingsType(settings)

    @classmethod
    def SupportedLanguages(cls) -> list[str]:
        """
        Canonical language names this aligner accepts.
        """
        raise NotImplementedError

    def AlignWords(self, audio_bytes : bytes, audio_format : str, transcript : str, language : str) -> list[WordTiming]:
        """
        Return per-word timings for transcript within the audio chunk.
        Timings are relative to the start of the chunk audio.
        """
        raise NotImplementedError


# Canonical aligner language names to qwen-asr language arguments
_ALIGNER_LANGUAGE_ALIASES : dict[str, str] = {
    'chinese': 'Chinese',
    'mandarin': 'Chinese',
    'putonghua': 'Chinese',
    'cantonese': 'Cantonese',
    'yue': 'Cantonese',
    'english': 'English',
    'french': 'French',
    'german': 'German',
    'deutsch': 'German',
    'italian': 'Italian',
    'japanese': 'Japanese',
    'korean': 'Korean',
    'portuguese': 'Portuguese',
    'russian': 'Russian',
    'spanish': 'Spanish',
    'espanol': 'Spanish',
}


def NormaliseAlignerLanguage(language : str|None, supported : list[str]) -> str|None:
    """
    Map a free-text language hint onto an aligner language, or None when
    the aligner cannot handle it (caller falls back to chunk-level lines).
    """
    if not language:
        return None

    canonical = _ALIGNER_LANGUAGE_ALIASES.get(language.strip().casefold(), language.strip())
    supported_cf = {s.casefold(): s for s in supported}
    return supported_cf.get(canonical.casefold())
