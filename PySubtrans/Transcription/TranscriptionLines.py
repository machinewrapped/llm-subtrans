from __future__ import annotations

import logging
import unicodedata
from datetime import timedelta

import regex

from PySubtrans.Helpers.Localization import _
from PySubtrans.Transcription.AudioExtractor import AudioChunk
from PySubtrans.Transcription.WordTiming import WordTiming
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionSegment

# Sentence-ending punctuation across CJK and latin scripts
SENTENCE_END_CHARS = frozenset('。！？!?\n…')

# Clause punctuation (and a period, which is not a hard boundary) that makes
# a good place to break an over-long utterance
CLAUSE_END_CHARS = frozenset('.,;:，、；：-–—')

# Lines shorter than this merge into their neighbour (bounds stay truthful)
MIN_LINE_SECONDS = 0.4

# A pause between words at least this long always starts a new line
PAUSE_SPLIT_SECONDS = 0.5

# Split-point scoring for over-long utterances: the pause at a boundary is
# the primary signal, weighted by how central the boundary is. The floor
# lets zero-pause boundaries still resolve by centrality; the bonuses and
# penalty nudge toward clause ends and away from stranding short words.
PAUSE_SCORE_FLOOR = 0.1
SENTENCE_END_BONUS = 0.5
CLAUSE_END_BONUS = 0.15
SHORT_WORD_PENALTY = 0.05
SHORT_WORD_CHARS = 3

CJK_BOUNDARY = regex.compile(r'[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\u3000-\u303f\uff00-\uffef]')


def SpanLabel(span : AudioChunk|TranscriptionSegment) -> str:
    """Human-readable start-end label for a chunk or segment, in seconds."""
    return f"{span.start.total_seconds():.1f}s-{span.end.total_seconds():.1f}s"


def NeedsSpace(previous : str, current : str) -> bool:
    """
    Whether a space is needed between two adjacent word tokens.

    Handles Latin scripts (space between words), CJK (no space between
    ideographs), and punctuation (no space before closing marks or after
    opening ones). Straight quotes use parity to distinguish open/close.

    Examples: ['Hello', 'world'] -> 'Hello world'
              ['你好', '世界']   -> '你好世界'
              ['He', 'said', '"Hello"'] -> 'He said "Hello"'
    """
    if not previous or not current or previous[-1].isspace() or current[0].isspace():
        return False

    last = previous[-1]
    first = current[0]
    if CJK_BOUNDARY.fullmatch(last) and CJK_BOUNDARY.fullmatch(first):
        return False

    last_category = unicodedata.category(last)
    first_category = unicodedata.category(first)
    # Straight quotes need the accumulated text to distinguish opening/closing.
    if first == '"':
        if previous.count('"') % 2:
            return False
    elif first_category.startswith('P') and first_category not in ('Ps', 'Pi'):
        return False

    if last in "'-\u2019" or last_category in ('Ps', 'Pi'):
        return False
    if last == '"':
        return previous.count('"') % 2 == 0
    return True


def JoinWords(words : list[str]) -> str:
    """Join aligned word tokens with language-appropriate spacing."""
    text = ""
    for word in words:
        if NeedsSpace(text, word):
            text += " "
        text += word
    return text.strip()


class TranscriptionLineBuilder:
    """
    Turns transcribed chunks into timed subtitle lines.

    Word timings group into utterances at pauses, speaker changes and
    sentence punctuation; utterances over the character or duration limit
    are split at their best pause. Provider sub-segments without word
    timings become rebased lines. Brief slivers merge into their
    neighbours. No provider or audio dependencies.
    """
    def __init__(self, max_line_chars : int, max_line_seconds : float, min_split_chars : int = 3):
        self.max_line_chars : int = max_line_chars
        self.max_line_seconds : float = max_line_seconds
        self.min_split_chars : int = min_split_chars

    def LinesForSegment(self, segment : TranscriptionSegment) -> list[TranscriptionSegment]:
        """
        Turn a transcribed chunk into timed subtitle lines.

        Word timings group into lines; provider sub-segments without word
        timings become rebased lines. A chunk with neither stays one line
        over its true chunk span: coarse but honest, and the text was
        already paid for, so it is kept rather than thrown away.
        """
        if segment.words:
            lines = self._group_words(segment.words, segment)
            return lines or [segment]

        if segment.parts:
            rebased = [self._rebase_part(part, segment) for part in segment.parts if part.text.strip()]
            for line in rebased:
                self.WarnIfOverlong(line)
            return rebased or [segment]

        self.WarnIfOverlong(segment)
        return [segment]

    def WarnIfOverlong(self, line : TranscriptionSegment) -> bool:
        """
        Flag engine-coarse spans no splitter can break up. Word-timed lines
        are already capped by grouping; over-long lines can only come from
        untimed engine segments, whose boundaries deserve a human glance.
        Returns True when a warning was logged.
        """
        duration = (line.end - line.start).total_seconds()
        if duration > self.max_line_seconds:
            logging.warning(_("Long transcription line ({:.1f}s, no word timings to split it): '{}'").format(
                duration, line.text[:120]))
            return True
        return False

    def MergeSlivers(self, lines : list[TranscriptionSegment]) -> list[TranscriptionSegment]:
        """Merge brief adjacent lines, preserving pauses and dialogue turns."""
        if len(lines) < 2:
            return lines

        merged : list[TranscriptionSegment] = []
        for line in lines:
            if merged and self._is_sliver(line) and self._close_enough(merged[-1], line):
                merged[-1] = self._merge_pair(merged[-1], line)
            else:
                merged.append(line)

        if len(merged) >= 2 and self._is_sliver(merged[0]) and self._close_enough(merged[0], merged[1]):
            merged[1] = self._merge_pair(merged[0], merged[1])
            merged.pop(0)
        return merged

    def _group_words(self, words : list[WordTiming], segment : TranscriptionSegment) -> list[TranscriptionSegment]:
        """
        Group chunk-relative word timings into subtitle lines. Words first
        split into utterances at real pauses, speaker changes and sentence
        punctuation; utterances that breach the character or duration
        limit are then split at their best pause, so a limit never
        strands a short tail. Offsets are rebased onto the chunk start.
        """
        lines : list[TranscriptionSegment] = []
        for utterance in self._split_utterances(words):
            for run in self._fit_utterance(utterance):
                lines.append(self._line_from_words(run, segment))

        return self.MergeSlivers(lines)

    def _split_utterances(self, words : list[WordTiming]) -> list[list[WordTiming]]:
        """Cut words at boundaries that apply regardless of line length."""
        utterances : list[list[WordTiming]] = []
        current : list[WordTiming] = []

        for word in words:
            if current and self._is_hard_boundary(current[-1], word):
                utterances.append(current)
                current = []
            current.append(word)

        if current:
            utterances.append(current)

        return utterances

    @staticmethod
    def _is_hard_boundary(previous : WordTiming, word : WordTiming) -> bool:
        """A long pause, a speaker change or the end of a sentence always starts a new line."""
        gap = (word.start - previous.end).total_seconds()
        speaker_changed = (word.speaker is not None and previous.speaker is not None
                           and word.speaker != previous.speaker)
        return (gap >= PAUSE_SPLIT_SECONDS
                or speaker_changed
                or bool(previous.text and previous.text[-1] in SENTENCE_END_CHARS))

    def _fits(self, words : list[WordTiming]) -> bool:
        """Whether a run of words is within the duration and character limits."""
        seconds = (words[-1].end - words[0].start).total_seconds()
        return seconds <= self.max_line_seconds and len(JoinWords([w.text for w in words])) <= self.max_line_chars

    def _fit_utterance(self, words : list[WordTiming]) -> list[list[WordTiming]]:
        """Split an over-long utterance at its best pauses until every piece fits."""
        if len(words) < 2 or self._fits(words):
            return [words]

        index = self._best_split_index(words)
        if index is None:
            return self._greedy_split(words)

        return self._fit_utterance(words[:index]) + self._fit_utterance(words[index:])

    def _best_split_index(self, words : list[WordTiming]) -> int|None:
        """
        Choose the boundary to split an utterance at. The pause at each
        boundary is the primary signal, weighted by closeness to the time
        midpoint, with bonuses for clause and sentence punctuation and a
        penalty for stranding a short word. Both halves must reach the
        minimum split length; None when no boundary qualifies.
        """
        start = words[0].start
        half_span = (words[-1].end - start).total_seconds() / 2.0
        best_index : int|None = None
        best_score : float = float('-inf')

        for index in range(1, len(words)):
            head = JoinWords([w.text for w in words[:index]])
            tail = JoinWords([w.text for w in words[index:]])
            if len(head) < self.min_split_chars or len(tail) < self.min_split_chars:
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
        """Fallback when no balanced split qualifies: break where the limit is breached."""
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

    def _line_from_words(self, words : list[WordTiming], segment : TranscriptionSegment) -> TranscriptionSegment:
        """Build one absolute-timed line from a run of chunk-relative words."""
        start, end = self._clamped_span(segment, words[0].start, words[-1].end)
        return TranscriptionSegment(start=start, end=end, text=JoinWords([w.text for w in words]),
                                    speaker=words[0].speaker or segment.speaker,
                                    language=segment.language)

    def _rebase_part(self, part : TranscriptionSegment, segment : TranscriptionSegment) -> TranscriptionSegment:
        """
        Rebase a chunk-relative sub-segment onto absolute media time.
        """
        start, end = self._clamped_span(segment, part.start, part.end)
        if part.confidence is not None and part.confidence < 0.4:
            logging.info(_("Chunk {}: low-confidence segment ({:.0%} no-speech probability): '{}'").format(
                SpanLabel(segment), 1.0 - part.confidence, part.text[:120]))
        return TranscriptionSegment(start=start, end=end, text=part.text.strip(),
                                    speaker=part.speaker or segment.speaker,
                                    language=part.language or segment.language,
                                    confidence=part.confidence)

    @staticmethod
    def _clamped_span(segment : TranscriptionSegment, start_offset : timedelta,
                      end_offset : timedelta) -> tuple[timedelta, timedelta]:
        """
        Rebase chunk-relative offsets onto the segment start, enforcing a
        minimum duration and never running past the segment end.
        """
        start = segment.start + start_offset
        end = segment.start + end_offset
        if end <= start:
            end = start + timedelta(seconds=MIN_LINE_SECONDS)
        if end > segment.end:
            end = segment.end
        return start, end

    @staticmethod
    def _is_sliver(line : TranscriptionSegment) -> bool:
        return (line.end - line.start).total_seconds() < MIN_LINE_SECONDS

    def _close_enough(self, first : TranscriptionSegment, second : TranscriptionSegment) -> bool:
        return (second.start - first.end).total_seconds() < PAUSE_SPLIT_SECONDS

    @staticmethod
    def _is_dialogue(line : TranscriptionSegment) -> bool:
        return line.text.startswith('- ') and '\n' in line.text

    def _merge_pair(self, first : TranscriptionSegment, second : TranscriptionSegment) -> TranscriptionSegment:
        """Combine two adjacent lines, formatting as dialogue when speakers differ."""
        mixed = (self._is_dialogue(first) or self._is_dialogue(second)
                 or (first.speaker is not None and second.speaker is not None
                     and first.speaker != second.speaker))
        if mixed:
            first_text = first.text if first.text.startswith('- ') else f'- {first.text}'
            second_text = second.text if second.text.startswith('- ') else f'- {second.text}'
            text = f'{first_text}\n{second_text}'
        else:
            text = JoinWords([first.text, second.text])
        return TranscriptionSegment(
            start=first.start, end=max(first.end, second.end), text=text,
            speaker=None if mixed else first.speaker or second.speaker,
            language=first.language or second.language)
