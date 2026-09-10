from __future__ import annotations

import logging
import unicodedata
from datetime import timedelta

import regex

from PySubtrans.Helpers.Localization import _
from PySubtrans.Transcription.AudioExtractor import AudioChunk
from PySubtrans.Transcription.TranscriptionAligner import WordTiming
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionSegment

# Sentence-ending punctuation across CJK and latin scripts
SENTENCE_END_CHARS = frozenset('。！？!?\n…')

# Lines shorter than this merge into their neighbour (bounds stay truthful)
MIN_LINE_SECONDS = 0.4

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

    Word timings group into lines bounded by character count, duration,
    sentence punctuation, pauses and speaker changes. Provider sub-segments
    without word timings become rebased lines. Brief slivers merge into
    their neighbours. No provider or audio dependencies.
    """
    def __init__(self, max_line_chars : int, max_line_seconds : float, word_gap_split : float):
        self.max_line_chars : int = max_line_chars
        self.max_line_seconds : float = max_line_seconds
        self.word_gap_split : float = word_gap_split

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
        Group chunk-relative word timings into subtitle lines. Every
        boundary and timing derives from aligned words: max characters,
        max duration, sentence punctuation and real inter-word pauses.
        Offsets are rebased onto the chunk start for absolute timings.
        """
        lines : list[TranscriptionSegment] = []
        current : list[WordTiming] = []

        for word in words:
            if current and self._should_break(current, word):
                lines.append(self._line_from_words(current, segment))
                current = []
            current.append(word)

        if current:
            lines.append(self._line_from_words(current, segment))

        return self.MergeSlivers(lines)

    def _should_break(self, current : list[WordTiming], word : WordTiming) -> bool:
        """Whether appending word to the current line would breach a line boundary."""
        previous = current[-1]
        gap = (word.start - previous.end).total_seconds()
        candidate = JoinWords([w.text for w in current] + [word.text])
        line_seconds = (word.end - current[0].start).total_seconds()
        first_speaker = current[0].speaker
        speaker_changed = (word.speaker is not None and first_speaker is not None
                           and word.speaker != first_speaker)
        return (len(candidate) > self.max_line_chars
                or line_seconds > self.max_line_seconds
                or gap >= self.word_gap_split
                or speaker_changed
                or bool(previous.text and previous.text[-1] in SENTENCE_END_CHARS))

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
        return (second.start - first.end).total_seconds() < self.word_gap_split

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
