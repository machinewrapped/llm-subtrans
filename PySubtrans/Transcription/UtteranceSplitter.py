from __future__ import annotations

from datetime import timedelta

from PySubtrans.Helpers.Speech import SENTENCE_END_CHARS
from PySubtrans.Helpers.Script import JoinWords
from PySubtrans.Transcription.LineSettings import LineSettings
from PySubtrans.Transcription.WordTiming import WordTiming

# Clause punctuation that makes a good place to break an over-long utterance.
# A period is only a soft boundary: short consecutive sentences read better together (docs/transcription-timing-correction.md).
CLAUSE_END_CHARS = frozenset('.,;:，、；：-–—')

# Split-point scoring for over-long utterances: the pause at a boundary is the primary signal, weighted by how central the boundary is.
# The floor lets zero-pause boundaries still resolve by centrality.
# The bonuses and penalty nudge toward clause ends and away from stranding short words.
PAUSE_SCORE_FLOOR = 0.1
SENTENCE_END_BONUS = 0.5
CLAUSE_END_BONUS = 0.15
SHORT_WORD_PENALTY = 0.05
SHORT_WORD_CHARS = 3


def WordSpan(words : list[WordTiming]) -> tuple[timedelta, timedelta]:
    """The earliest start and latest end of a run of words."""
    # Engine timings need not run in step with word order, so the first and last word do not bound the run
    return min(word.start for word in words), max(word.end for word in words)


def AttachPunctuation(words : list[WordTiming]) -> list[WordTiming]:
    """Fold punctuation-only words into the word before them, so a split never starts with one."""
    attached : list[WordTiming] = []
    for word in words:
        if attached and word.is_punctuation:
            # Punctuation is not spoken, so the word keeps its own end
            previous = attached[-1]
            attached[-1] = WordTiming(text=previous.text + word.text, start=previous.start,
                                      end=previous.end, speaker=previous.speaker)
        else:
            attached.append(word)

    return attached


class UtteranceSplitter:
    """Divides timed words into utterances, and utterances into runs that fit on a line."""
    def __init__(self, settings : LineSettings):
        self.settings : LineSettings = settings

    def IsHardBoundary(self, previous : WordTiming, word : WordTiming) -> bool:
        """A long pause, a speaker change or the end of a sentence always starts a new line."""
        gap = (word.start - previous.end).total_seconds()
        speaker_changed = (word.speaker is not None and previous.speaker is not None
                           and word.speaker != previous.speaker)

        return (gap >= self.settings.EligibleGap(previous.speaker, word.speaker)
                or speaker_changed
                or bool(previous.text and previous.text[-1] in SENTENCE_END_CHARS))

    def SplitUtterances(self, words : list[WordTiming]) -> list[list[WordTiming]]:
        """Cut words at hard boundaries, regardless of line length."""
        utterances : list[list[WordTiming]] = []
        current : list[WordTiming] = []

        for word in words:
            if current and self.IsHardBoundary(current[-1], word):
                utterances.append(current)
                current = []
            current.append(word)

        if current:
            utterances.append(current)

        return utterances

    def FitUtterance(self, words : list[WordTiming]) -> list[list[WordTiming]]:
        """Split an over-long utterance at its best boundaries until every piece fits."""
        if len(words) < 2 or self._fits(words):
            return [words]

        index = self._best_split_index(words)
        if index is None:
            return self._greedy_split(words)

        return self.FitUtterance(words[:index]) + self.FitUtterance(words[index:])

    def _fits(self, words : list[WordTiming]) -> bool:
        """Whether a run of words is within the duration and character limits."""
        start, end = WordSpan(words)
        seconds = (end - start).total_seconds()
        return seconds <= self.settings.max_line_seconds and len(JoinWords([w.text for w in words])) <= self.settings.max_line_chars

    def _best_split_index(self, words : list[WordTiming]) -> int|None:
        """The highest-scoring boundary that leaves both halves long enough, if any."""
        start, end = WordSpan(words)
        half_span = (end - start).total_seconds() / 2.0
        best_index : int|None = None
        best_score : float = float('-inf')

        for index in range(1, len(words)):
            head = JoinWords([w.text for w in words[:index]])
            tail = JoinWords([w.text for w in words[index:]])
            if len(head) < self.settings.min_split_chars or len(tail) < self.settings.min_split_chars:
                continue

            previous, word = words[index - 1], words[index]
            pause = max(0.0, (word.start - previous.end).total_seconds())
            position = (previous.end - start).total_seconds()
            centrality = 1.0 - abs(position - half_span) / half_span if half_span > 0.0 else 1.0
            score = (pause + PAUSE_SCORE_FLOOR) * max(0.0, centrality)

            last = previous.text[-1] if previous.text else ''
            if last in SENTENCE_END_CHARS:
                score += SENTENCE_END_BONUS
            elif last in CLAUSE_END_CHARS:
                score += CLAUSE_END_BONUS

            if sum(1 for c in previous.text if c.isalnum()) <= SHORT_WORD_CHARS:
                score -= SHORT_WORD_PENALTY

            if score > best_score:
                best_index, best_score = index, score

        return best_index

    def _greedy_split(self, words : list[WordTiming]) -> list[list[WordTiming]]:
        """Break wherever a limit is breached, when no balanced split qualifies."""
        pieces : list[list[WordTiming]] = []
        current : list[WordTiming] = []

        for word in words:
            if current and not self._fits(current + [word]):
                pieces.append(current)
                current = []
            current.append(word)

        if current:
            pieces.append(current)

        return pieces
