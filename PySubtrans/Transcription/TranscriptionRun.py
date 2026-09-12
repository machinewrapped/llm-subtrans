import logging
from datetime import timedelta

from PySubtrans.Helpers.Localization import _
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.Subtitles import Subtitles
from PySubtrans.Transcription.AudioExtractor import AudioChunk
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionSegment

class TranscriptionRun:
    """
    Mutable state for one TranscribeMedia call: accumulated lines,
    resume position, cost and failure bookkeeping.
    """
    def __init__(self, prior_subtitles : Subtitles|None):
        self.lines : list[SubtitleLine] = []
        self.line_number : int = 0
        self.resume_after : timedelta|None = None
        self.transcribed : int = 0
        self.chunks_done : int = 0
        self.consecutive_failures : int = 0
        self.had_failures : bool = False
        self.error : SubtitleError|None = None
        self.total_cost : float = 0.0
        self.audio_total_seconds : float = 0.0

        if prior_subtitles and prior_subtitles.originals:
            self.lines.extend(prior_subtitles.originals)
            self.line_number = max((line.number or 0) for line in self.lines)
            self.resume_after = prior_subtitles.originals[-1].end
            self.transcribed = prior_subtitles.linecount
            logging.info(_("Resuming transcription after {}").format(self.resume_after))

    def AlreadyDone(self, chunk : AudioChunk) -> bool:
        """Whether a prior run already covered this chunk."""
        return self.resume_after is not None and chunk.end <= self.resume_after

    def AddLine(self, segment : TranscriptionSegment) -> SubtitleLine|None:
        """
        Append a transcribed line, unless it precedes the resume point.
        Returns the new line, or None when skipped.
        """
        if self.resume_after is not None and segment.start < self.resume_after:
            return None

        self.line_number += 1
        metadata = {'speaker': segment.speaker} if segment.speaker else None
        line = SubtitleLine.Construct(self.line_number, segment.start, segment.end, segment.text, metadata)
        self.lines.append(line)
        self.transcribed += 1
        return line

    def AudioPosition(self, chunk : AudioChunk) -> float:
        """Seconds of audio processed once this chunk is done, clamped to the total."""
        return min(self.audio_total_seconds, max(0.0, chunk.end.total_seconds()))