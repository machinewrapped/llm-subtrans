from dataclasses import dataclass
from enum import Enum

from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Subtitles import Subtitles

class TranscriptionStatus(str, Enum):
    """Final state of a transcription run."""
    IDLE = "idle"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    FAILED = "failed"

@dataclass
class TranscriptionOutcome:
    """
    Result of one transcription run.

    COMPLETED and INCOMPLETE outcomes carry subtitles (partial ones for
    INCOMPLETE, which can be resumed by passing them back as
    prior_subtitles). FAILED outcomes carry the error and no subtitles.
    """
    status : TranscriptionStatus
    subtitles : Subtitles|None = None
    error : SubtitleError|None = None
    transcribed_lines : int = 0
    total_cost : float = 0.0

    @property
    def succeeded(self) -> bool:
        return self.status is TranscriptionStatus.COMPLETED