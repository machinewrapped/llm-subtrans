from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

import regex

# A word made of nothing but punctuation and spacing
PUNCTUATION_ONLY = regex.compile(r'^[\p{P}\s]+$')

@dataclass
class WordTiming:
    """
    A single aligned word (or character) with absolute media timings.
    """
    text : str = ""
    start : timedelta = field(default_factory=lambda: timedelta(seconds=0))
    end : timedelta = field(default_factory=lambda: timedelta(seconds=0))
    speaker : str|None = None

    @property
    def is_punctuation(self) -> bool:
        """Whether the word is only punctuation, which engines time but nobody speaks."""
        return bool(PUNCTUATION_ONLY.match(self.text))
