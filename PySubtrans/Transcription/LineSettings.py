from __future__ import annotations

from dataclasses import dataclass

from PySubtrans.Transcription.WordAlignment import WordCoverage

# Widest gap that can fall within a line when the speaker is unknown or changes
DEFAULT_MERGE_ELIGIBLE_GAP_SECONDS = 0.5

# A pause within one speaker's turn is not a break, so it is given more room
DEFAULT_SAME_SPEAKER_MERGE_ELIGIBLE_GAP_SECONDS = 1.0

# Space left between a line extended into a pause and the line after it
DEFAULT_MIN_GAP_SECONDS = 0.05

# Provider timings are trusted unless a provider has shown they need correcting
DEFAULT_TIMING_CORRECTION_FACTOR = 0.0


@dataclass(frozen=True)
class LineSettings:
    """Limits a transcribed subtitle line is held to, and how its neighbours may be merged."""
    max_line_chars : int
    max_line_seconds : float
    min_split_chars : int = 3
    min_line_seconds : float = 0.8
    merge_eligible_gap : float = DEFAULT_MERGE_ELIGIBLE_GAP_SECONDS
    same_speaker_merge_eligible_gap : float = DEFAULT_SAME_SPEAKER_MERGE_ELIGIBLE_GAP_SECONDS
    max_newlines : int = 2
    can_merge_different_speakers : bool = True
    min_gap : float = DEFAULT_MIN_GAP_SECONDS
    word_coverage : WordCoverage = WordCoverage.COMPLETE
    timing_correction_factor : float = DEFAULT_TIMING_CORRECTION_FACTOR

    def EligibleGap(self, first_speaker : str|None, second_speaker : str|None) -> float:
        """The widest gap that still leaves two lines eligible to be one."""
        if first_speaker is not None and first_speaker == second_speaker:
            return self.same_speaker_merge_eligible_gap

        return self.merge_eligible_gap
