from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

@dataclass
class WordTiming:
    """
    A single aligned word (or character) with absolute media timings.
    """
    text : str = ""
    start : timedelta = field(default_factory=lambda: timedelta(seconds=0))
    end : timedelta = field(default_factory=lambda: timedelta(seconds=0))
    speaker : str|None = None

