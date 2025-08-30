from __future__ import annotations

from typing import Any

from PySubtitle.SubtitleLine import SubtitleLine

class SubtitleData:
    """
    Container for subtitle lines and file-level metadata.
    
    This class encapsulates both the individual subtitle lines and any
    format-specific metadata needed to preserve file structure during
    parsing and composition operations.
    """
    
    def __init__(self, lines: list[SubtitleLine] | None = None, metadata: dict[str, Any] | None = None, start_line_number: int | None = None):
        self.lines: list[SubtitleLine] = lines or []
        self.metadata: dict[str, Any] = metadata or {}
        self.start_line_number: int | None = start_line_number