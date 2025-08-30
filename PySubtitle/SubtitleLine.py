from __future__ import annotations
from copy import deepcopy
from datetime import timedelta
import logging
from os import linesep
from typing import Any
import regex

from PySubtitle.Helpers.Localization import _
from PySubtitle.SubtitleError import SubtitleError
from PySubtitle.Helpers.Time import GetTimeDelta, GetTimeDeltaSafe, TimedeltaToSrtTimestamp, TimedeltaToText

# Global regex pattern for SRT parsing (compiled once for performance)
SRT_PATTERN = regex.compile(
    r'^(?P<index>\d+)\s*\n'
    r'(?P<start>\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(?P<end>\d{2}:\d{2}:\d{2},\d{3})\s*\n'
    r'(?P<content>.*?)$',
    regex.DOTALL
)

class SubtitleLine:
    """
    Represents a single subtitle line with timing, content, and metadata.
    This is the internal representation used throughout the application.
    """
    def __init__(self, line : SubtitleLine|str|dict|None = None, translation : str|None = None, original : str|None = None):
        # Core subtitle properties 
        self._index: int|None = None
        self._start: timedelta|None = None
        self._end: timedelta|None = None
        self.content: str|None = None
        self.metadata: dict[str, Any] = {}
        
        # Additional properties
        self.translation : str|None = translation
        self.original : str|None = original
        self._duration : timedelta|None = None

        if isinstance(line, SubtitleLine):
            self._index = line._index
            self._start = line._start
            self._end = line._end
            self.content = line.text
            self._duration = line._duration
            self.original = original if original is not None else line.original
            self.translation = translation if translation is not None else line.translation
            self.metadata = line.metadata.copy()

        elif isinstance(line, dict):
            if 'line' in line:
                # Backwards compatibility: extract from line property 
                self._parse_from_string(str(line['line']))
            else:
                # New format: use individual properties
                self._index = int(line.get('index') or line.get('number') or 0)
                start_time = line.get('start')
                end_time = line.get('end')
                self._start = GetTimeDeltaSafe(start_time)
                self._end = GetTimeDeltaSafe(end_time)
                self.text = line.get('content') or line.get('text') or line.get('body')

            self.metadata = deepcopy(line.get('metadata', {}))
            
            # Override with provided translation/original if specified
            self.translation = translation if translation is not None else line.get('translation')
            self.original = original if original is not None else line.get('original')

        elif line is not None:
            # Parse from string
            self._parse_from_string(str(line))

    def __str__(self) -> str:
        return f"{self.number}:{self.srt_start}-->{self.srt_end}: {self.text}" if self._start is not None and self._end is not None else "Invalid SubtitleLine"

    def __repr__(self) -> str:
        return f"[Line {self.number}] {TimedeltaToText(self.start)}, {repr(self.text)}"

    def __eq__(self, other : 'Any|SubtitleLine') -> bool:
        if not isinstance(other, SubtitleLine):
            return False
        return (self.number == other.number and 
                self.start == other.start and 
                self.end == other.end and 
                self.text == other.text)

    def copy(self) -> SubtitleLine:
        """Create a copy of this subtitle line."""
        new_line = SubtitleLine()
        new_line._index = self._index
        new_line._start = self._start
        new_line._end = self._end
        new_line.content = self.content
        new_line.translation = self.translation
        new_line.original = self.original
        new_line._duration = self._duration
        new_line.metadata = deepcopy(self.metadata)
        return new_line

    @property
    def start(self) -> timedelta:
        return self._start or timedelta(seconds=0)

    @property
    def end(self) -> timedelta:
        return self._end or timedelta(seconds=0)

    @property
    def key(self) -> int|str:
        return self.number if self.number else str(self.start)

    @property
    def number(self) -> int:
        return self._index or 0

    @property
    def text(self) -> str|None:
        return self.content

    @property
    def text_normalized(self) -> str|None:
        return self.text.replace(linesep, '\n').strip() if self.text else None

    @property
    def srt_start(self) -> str:
        return TimedeltaToSrtTimestamp(self.start) or "00:00.00,000"

    @property
    def txt_start(self) -> str:
        return TimedeltaToText(self.start) or _("Invalid timestamp")

    @property
    def srt_end(self) -> str:
        return TimedeltaToSrtTimestamp(self.end) or "00:00.00,000"

    @property
    def txt_end(self) -> str:
        return TimedeltaToText(self.end) or _("Invalid timestamp")

    @property
    def duration(self) -> timedelta:
        if not self._duration:
            self._duration = self.end - self.start if self._start is not None and self.end else timedelta(seconds=0)
        return self._duration

    @property
    def txt_duration(self) -> str:
        return TimedeltaToText(self.duration)

    @property
    def translated(self) -> SubtitleLine|None:
        if self.translation is None:
            return None
        return SubtitleLine.Construct(self.number, self.start, self.end, self.translation, self.metadata)

    @number.setter
    def number(self, value : int|str|None):
        self._index = int(value) if value is not None else None

    @text.setter
    def text(self, text : str|None):
        self.content = str(text).strip() if text else None

    @start.setter
    def start(self, time : timedelta|str):
        """Set the start time, handling string conversion."""
        new_time = GetTimeDelta(time, raise_exception=False)

        if isinstance(new_time, Exception):
            raise SubtitleError(f"Invalid start time: {time}", error=new_time)

        self._start = new_time
        self._duration = None

    @end.setter
    def end(self, time : timedelta|str):
        """Set the end time, handling string conversion."""
        new_time = GetTimeDelta(time, raise_exception=False)

        if isinstance(new_time, Exception):
            raise SubtitleError(f"Invalid end time: {time}", error=new_time)

        self._end = new_time
        self._duration = None

    @duration.setter
    def duration(self, duration : timedelta|str):
        """Set the duration and update end time accordingly."""
        tdelta : timedelta|Exception|None = GetTimeDelta(duration)
        if isinstance(tdelta, Exception):
            raise SubtitleError(f"Invalid duration", error=tdelta)

        self._duration = tdelta or timedelta(seconds=0)
        if self._start is not None:
            self._end = self._start + self._duration

    @translated.setter
    def translated(self, translated : SubtitleLine|str|None):
        self.translation = SubtitleLine(translated).text if translated else None

    def _parse_from_string(self, line_str: str) -> None:
        """
        Parse subtitle line from basic SRT format string.
        """
        if not line_str.strip():
            raise SubtitleError(_("Invalid subtitle line format: {}").format("empty line"))
        
        # Pattern matches: {index}\n{start} --> {end}\n{content (multiline)}
        match = SRT_PATTERN.match(line_str)
        if not match:
            raise SubtitleError(_("Invalid subtitle line format: {}").format(line_str))

        try:
            self._index = int(match.group('index'))
        except ValueError as e:
            raise SubtitleError(_("Invalid subtitle line index: {}").format(match.group('index')), error=e)
        
        self._start = GetTimeDeltaSafe(match.group('start'))
        self._end = GetTimeDeltaSafe(match.group('end'))
            
        self.content = match.group('content').strip()

    @classmethod
    def Construct(cls, number : int|str|None, start : timedelta|str|None, end : timedelta|str|None, text : str, metadata : dict[str,Any]|None = None) -> SubtitleLine:
        if number is None:
            logging.warning("Missing line index")

        t_start : timedelta|Exception|None = GetTimeDelta(start)
        t_end : timedelta|Exception|None = GetTimeDelta(end)
        if isinstance(t_start, Exception):
            raise t_start
        if isinstance(t_end, Exception):
            raise t_end

        legal_text : str = text.strip() if text else ""
        
        line = SubtitleLine()
        line.number = number
        line.start = t_start or timedelta(seconds=0)
        line.end = t_end or timedelta(seconds=0)
        line.text = legal_text
        line.metadata = metadata or {}
        return line
