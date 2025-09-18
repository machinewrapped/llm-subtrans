from __future__ import annotations

from typing import Any

from PySubtrans.SubtitleLine import SubtitleLine


class SubtitleData:
    """
    Format-agnostic container for subtitle lines and file-level metadata.

    Attributes:
        lines (list[SubtitleLine]): List of subtitle lines in the LLM-Subtrans internal representation
        metadata (dict[str, Any]): File-level metadata extracted from or required by specific formats
        start_line_number (int|None): Optional base line number for formats that support line numbering
        detected_format (str|None): Optional detected file format/extension (e.g. '.srt')
    """

    def __init__(self, lines : list[SubtitleLine]|None = None, metadata : dict[str, Any]|None = None, start_line_number : int|None = None, detected_format : str|None = None
    ):
        self.lines : list[SubtitleLine] = lines or []
        self.metadata : dict[str, Any] = metadata or {}
        self.start_line_number : int|None = start_line_number
        self.detected_format : str|None = detected_format

