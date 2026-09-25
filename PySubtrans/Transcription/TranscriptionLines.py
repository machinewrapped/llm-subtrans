from __future__ import annotations

import logging
from datetime import timedelta

from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Script import JoinWords
from PySubtrans.Helpers.Speech import EstimateSpeechSeconds
from PySubtrans.Helpers.Text import CompactText, CutText
from PySubtrans.Helpers.Time import SpanLabel
from PySubtrans.Transcription.LineMerger import LineMerger
from PySubtrans.Transcription.LineSettings import LineSettings
from PySubtrans.Transcription.TranscriptCutter import TranscriptCutter
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionSegment
from PySubtrans.Transcription.UtteranceSplitter import AttachPunctuation, UtteranceSplitter, WordSpan
from PySubtrans.Transcription.WordAlignment import AlignWords, AssignToRanges
from PySubtrans.Transcription.WordTiming import WordTiming

# A word is capped at this multiple of its estimated speaking time
WORD_CAP_MULTIPLE = 4.0
MIN_WORD_CAP_SECONDS = 1.0

# A word lasting this multiple of its estimate is an aligner failure, and is not used for timing
UNRELIABLE_WORD_MULTIPLE = 8.0
MIN_UNRELIABLE_WORD_SECONDS = 2.0

# Parts below this confidence are logged, since the engine thought they were probably not speech
LOW_CONFIDENCE = 0.4


class TranscriptionLineBuilder:
    """
    Turns transcribed chunks into timed subtitle lines.
    Provider sub-segments are the lines when there are any; otherwise the chunk transcript is cut into parts.
    Word timings only time and split them, or form the lines themselves when there is no transcript.
    """
    def __init__(self, settings : LineSettings):
        self.settings : LineSettings = settings
        self.splitter : UtteranceSplitter = UtteranceSplitter(settings)
        self.merger : LineMerger = LineMerger(settings)
        self.cutter : TranscriptCutter = TranscriptCutter(settings, self.splitter)

    def LinesForSegment(self, segment : TranscriptionSegment) -> list[TranscriptionSegment]:
        """Turn a transcribed chunk into timed subtitle lines."""
        if segment.parts:
            return self._lines_from_parts(segment)

        if segment.text.strip():
            return self._lines_from_transcript(segment)

        if segment.words:
            return self._lines_from_words(segment) or [segment]

        self.WarnIfOverlong(segment)
        return [segment]

    def WarnIfOverlong(self, line : TranscriptionSegment) -> bool:
        """Log a warning for a line over the duration limit, returning whether one was logged."""
        # Only untimed engine spans can get here too long, and their boundaries deserve a human glance
        duration = (line.end - line.start).total_seconds()
        if duration > self.settings.max_line_seconds:
            logging.warning(_("Long transcription line ({:.1f}s, no word timings to split it): '{}'").format(
                duration, line.text[:120]))
            return True

        return False

    def _lines_from_parts(self, segment : TranscriptionSegment) -> list[TranscriptionSegment]:
        """Lines from the provider's sub-segments."""
        parts = [part for part in segment.parts if part.text.strip()]
        return self._fit_parts(segment, parts, self._assign_words(parts, self._timing_words(segment.words)))

    def _lines_from_transcript(self, segment : TranscriptionSegment) -> list[TranscriptionSegment]:
        """Lines from the chunk transcript, cut into parts."""
        parts, assigned = self.cutter.Cut(segment, self._timing_words(segment.words))

        if not any(assigned):
            logging.info(_("Chunk {}: no word timings match the transcript, so lines are placed by length").format(
                SpanLabel(segment.start, segment.end)))

        return self._fit_parts(segment, parts, assigned)

    def _lines_from_words(self, segment : TranscriptionSegment) -> list[TranscriptionSegment]:
        """Lines grouped from word timings alone, at hard boundaries and then at the best pauses."""
        words = [self._capped_word(word) for word in segment.words]

        lines : list[TranscriptionSegment] = []
        for utterance in self.splitter.SplitUtterances(words):
            for run in self.splitter.FitUtterance(utterance):
                lines.append(self._line_from_words(run, segment))

        return self.merger.MergeSlivers(lines, limit=segment.end)

    def _fit_parts(self, segment : TranscriptionSegment, parts : list[TranscriptionSegment],
                   assigned : list[list[WordTiming]]) -> list[TranscriptionSegment]:
        """Turn chunk-relative parts and their words into lines, then merge slivers."""
        lines : list[TranscriptionSegment] = []
        for part, part_words in zip(parts, assigned):
            lines.extend(self._fit_part(part, part_words, segment))

        # Providers that segment for us still strand fragments, which translate badly in isolation
        merged = self.merger.MergeSlivers(lines, limit=segment.end)
        for line in merged:
            self.WarnIfOverlong(line)

        return merged or [segment]

    def _fit_part(self, part : TranscriptionSegment, words : list[WordTiming],
                  segment : TranscriptionSegment) -> list[TranscriptionSegment]:
        """Rebase a part, splitting it at its words when it runs over a limit."""
        line = self._rebase_part(part, segment)
        duration = (line.end - line.start).total_seconds()
        if not words or (duration <= self.settings.max_line_seconds and len(line.text) <= self.settings.max_line_chars):
            return [line]

        # The text always comes from the part; words only decide where it is cut and when each piece is shown
        pieces = self.splitter.FitUtterance(AttachPunctuation(words))
        texts = CutText(line.text, [sum(len(CompactText(word.text)) for word in piece) for piece in pieces])

        lines : list[TranscriptionSegment] = []
        for piece, text in zip(pieces, texts):
            start, end = self._clamped_span(segment, *WordSpan(piece))
            lines.append(TranscriptionSegment(start=start, end=end, text=text, speaker=line.speaker,
                                              language=line.language, confidence=line.confidence))

        return lines

    def _assign_words(self, parts : list[TranscriptionSegment], words : list[WordTiming]) -> list[list[WordTiming]]:
        """Share words out among the parts that transcribe them, matching text in order."""
        # Timings are not consulted, since they are the unreliable half
        text = '\n'.join(part.text for part in parts)

        ranges : list[tuple[int, int]] = []
        position = 0
        for part in parts:
            ranges.append((position, position + len(part.text)))
            position += len(part.text) + 1

        return AssignToRanges(text, ranges, AlignWords(text, words))

    def _timing_words(self, words : list[WordTiming]) -> list[WordTiming]:
        """Capped words, without those whose span is too long for their text to be real."""
        reliable = [word for word in words if (word.end - word.start).total_seconds()
                    <= max(MIN_UNRELIABLE_WORD_SECONDS, UNRELIABLE_WORD_MULTIPLE * EstimateSpeechSeconds(word.text))]
        return [self._capped_word(word) for word in reliable]

    def _capped_word(self, word : WordTiming) -> WordTiming:
        """Limit a word to a generous multiple of its speaking time, and never beyond a whole line."""
        # Engines occasionally stamp a word across most of a chunk
        cap = min(self.settings.max_line_seconds, max(MIN_WORD_CAP_SECONDS, WORD_CAP_MULTIPLE * EstimateSpeechSeconds(word.text)))
        if (word.end - word.start).total_seconds() <= cap:
            return word

        return WordTiming(text=word.text, start=word.start, end=word.start + timedelta(seconds=cap), speaker=word.speaker)

    def _line_from_words(self, words : list[WordTiming], segment : TranscriptionSegment) -> TranscriptionSegment:
        """Build one absolute-timed line from a run of chunk-relative words."""
        start, end = self._clamped_span(segment, *WordSpan(words))
        return TranscriptionSegment(start=start, end=end, text=JoinWords([w.text for w in words]),
                                    speaker=words[0].speaker or segment.speaker,
                                    language=segment.language)

    def _rebase_part(self, part : TranscriptionSegment, segment : TranscriptionSegment) -> TranscriptionSegment:
        """Rebase a chunk-relative sub-segment onto absolute media time."""
        start, end = self._clamped_span(segment, part.start, part.end)
        if part.confidence is not None and part.confidence < LOW_CONFIDENCE:
            logging.info(_("Chunk {}: low-confidence segment ({:.0%} no-speech probability): '{}'").format(
                SpanLabel(segment.start, segment.end), 1.0 - part.confidence, part.text[:120]))

        return TranscriptionSegment(start=start, end=end, text=part.text.strip(),
                                    speaker=part.speaker or segment.speaker,
                                    language=part.language or segment.language,
                                    confidence=part.confidence)

    def _clamped_span(self, segment : TranscriptionSegment, start_offset : timedelta,
                      end_offset : timedelta) -> tuple[timedelta, timedelta]:
        """Rebase chunk-relative offsets onto the segment, with a minimum duration and never past its end."""
        start = segment.start + start_offset
        end = segment.start + end_offset

        if start > segment.end:
            start = segment.end
        if end <= start:
            end = start + timedelta(seconds=self.settings.min_line_seconds)
        if end > segment.end:
            end = segment.end

        return start, end
