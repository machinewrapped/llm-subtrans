from __future__ import annotations

from typing import Any

from PySubtitle.SubtitleLine import SubtitleLine


class SubtitleData:
    """Container for subtitle lines and file-level metadata."""

    def __init__(
        self,
        lines : list[SubtitleLine]|None = None,
        metadata : dict[str, Any]|None = None,
        start_line_number : int|None = None,
        detected_format : str|None = None
    ):
        self.lines : list[SubtitleLine] = lines or []
        self.metadata : dict[str, Any] = metadata or {}
        self.start_line_number : int|None = start_line_number
        self.detected_format : str|None = detected_format

