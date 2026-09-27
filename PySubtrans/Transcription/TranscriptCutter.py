from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import NamedTuple

from PySubtrans.Helpers.Speech import (SPOKEN_CHAR, EndsSentence, EstimateSpeechSeconds, NominalSecondsPerChar,
                                       SentenceEnds, SentenceRanges)
from PySubtrans.Helpers.Text import CompactText
from PySubtrans.Transcription.LineSettings import LineSettings
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionSegment
from PySubtrans.Transcription.UtteranceSplitter import UtteranceSplitter
from PySubtrans.Transcription.WordAlignment import (AlignedWord, AlignWords, AssignToRanges, CutPoints,
                                                    SplitAtSpeakerChanges, TimedSentenceRanges, WordCoverage)
from PySubtrans.Transcription.WordTiming import WordTiming

# A spoken word lasting under this fraction of its estimate has been squeezed by the aligner, and is not used for timing
SQUEEZED_WORD_FRACTION = 0.1

# A part whose matched words spell at least this share of its text is timed by them alone
WELL_COVERED_FRACTION = 0.8


class PartCoverage(NamedTuple):
    """Spoken characters in a part: all of them, those its words matched, and those before its first matched word."""
    spoken : int
    matched : int
    leading : int


def IsSqueezed(word : WordTiming) -> bool:
    """Whether a spoken word is far too brief for its text, as when an aligner crams a run of words together."""
    if word.is_punctuation:
        return False

    return (word.end - word.start).total_seconds() < SQUEEZED_WORD_FRACTION * EstimateSpeechSeconds(word.text)


def ExtendToPunctuation(words : list[WordTiming]) -> list[WordTiming]:
    """Extend each word to the end of any punctuation-only words after it."""
    # Engines that time punctuation place it where the utterance ends, so a part closed by it ends there too
    extended : list[WordTiming] = []
    spoken : int|None = None

    for word in words:
        if not word.is_punctuation:
            spoken = len(extended)
        elif spoken is not None and word.end > extended[spoken].end:
            previous = extended[spoken]
            extended[spoken] = WordTiming(text=previous.text, start=previous.start, end=word.end, speaker=previous.speaker)
        extended.append(word)

    return extended


def MajoritySpeaker(words : list[WordTiming]) -> str|None:
    """The speaker of most of the words, if any carry one."""
    speakers = Counter(word.speaker for word in words if word.speaker is not None)
    return speakers.most_common(1)[0][0] if speakers else None


def CharacterCounts(text : str, ranges : list[tuple[int, int]], aligned : list[AlignedWord]) -> list[PartCoverage]:
    """How much of each range of the text its aligned words spell."""
    counts : list[PartCoverage] = []
    for start, end in ranges:
        members = [word for word in aligned if start <= word.start < end]
        spoken = sum(1 for char in text[start:end] if SPOKEN_CHAR.match(char))
        matched = sum(word.matched for word in members)
        leading = sum(1 for char in text[start:members[0].start] if SPOKEN_CHAR.match(char)) if members else 0
        counts.append(PartCoverage(spoken, matched, leading))

    return counts


class TranscriptCutter:
    """Cuts a chunk transcript into chunk-relative parts timed by its words."""
    def __init__(self, settings : LineSettings, splitter : UtteranceSplitter):
        self.settings : LineSettings = settings
        self.splitter : UtteranceSplitter = splitter

    def Cut(self, segment : TranscriptionSegment, words : list[WordTiming]) -> tuple[list[TranscriptionSegment], list[list[WordTiming]]]:
        """Cut the transcript into timed parts, each with the words that spell it."""
        # The transcript is the text; words drop characters and punctuation, so they only give the timing
        text = segment.text.strip()
        duration = segment.end - segment.start

        if self.settings.word_coverage == WordCoverage.PARTIAL:
            # An aligner that drops text also crams runs of words into a moment
            words = [word for word in words if not IsSqueezed(word)]

        aligned = AlignWords(text, ExtendToPunctuation(words))
        ranges = self._ranges(text, aligned)
        assigned = AssignToRanges(text, ranges, aligned)
        parts = [TranscriptionSegment(text=text[start:end].strip(), speaker=MajoritySpeaker(part_words))
                 for (start, end), part_words in zip(ranges, assigned)]

        self._time_parts(parts, assigned, duration)
        if self.settings.word_coverage == WordCoverage.PARTIAL:
            self._fill_sparse_parts(parts, CharacterCounts(text, ranges, aligned), duration)

        kept = [index for index, part in enumerate(parts) if part.text]
        return [parts[index] for index in kept], [assigned[index] for index in kept]

    def _ranges(self, text : str, aligned : list[AlignedWord]) -> list[tuple[int, int]]:
        """Where the transcript is cut into parts."""
        # Without matched words only the punctuation can divide the transcript
        if not aligned:
            return SentenceRanges(text, SentenceEnds.ALL)

        sentences = TimedSentenceRanges(text, aligned)
        if len(sentences) > 1 or EndsSentence(text):
            return SplitAtSpeakerChanges(text, sentences, aligned)

        return self._pause_ranges(text, aligned)

    def _pause_ranges(self, text : str, aligned : list[AlignedWord]) -> list[tuple[int, int]]:
        """Ranges of an unpunctuated text, cut where its words pause or change speaker."""
        cuts = CutPoints(text, aligned, 0, len(text))
        ranges : list[tuple[int, int]] = []
        start = 0

        for index in range(1, len(aligned)):
            if self.splitter.IsHardBoundary(aligned[index - 1].word, aligned[index].word):
                ranges.append((start, cuts[index]))
                start = cuts[index]

        ranges.append((start, len(text)))
        return ranges

    def _time_parts(self, parts : list[TranscriptionSegment], assigned : list[list[WordTiming]], duration : timedelta) -> None:
        """Set each part's chunk-relative span from its words, placing parts without words between their neighbours."""
        if not any(assigned):
            self._spread_untimed(parts, duration)
            return

        for part, words in zip(parts, assigned):
            if words:
                part.start = min(word.start for word in words)
                part.end = max(word.end for word in words)

        self._place_untimed_runs(parts, assigned, duration)

    def _spread_untimed(self, parts : list[TranscriptionSegment], duration : timedelta) -> None:
        """Give each part its share of the chunk by characters, up to a line's length or the time its text takes to say."""
        # Text that takes longer to say than a line may last is left long, so that subtitle post-processing splits it by duration
        total = sum(len(CompactText(part.text)) for part in parts) or 1
        longest = timedelta(seconds=self.settings.max_line_seconds)
        position = 0

        for part in parts:
            part.start = duration * (position / total)
            position += len(CompactText(part.text))
            speech = timedelta(seconds=EstimateSpeechSeconds(part.text))
            part.end = min(duration * (position / total), part.start + max(longest, speech))

    def _place_untimed_runs(self, parts : list[TranscriptionSegment], assigned : list[list[WordTiming]], duration : timedelta) -> None:
        """Share the time between timed parts among the untimed parts in it, by characters."""
        index = 0
        while index < len(parts):
            if assigned[index]:
                index += 1
                continue

            run_end = index
            while run_end < len(parts) and not assigned[run_end]:
                run_end += 1

            after = parts[index - 1].end if index > 0 else timedelta(0)
            before = parts[run_end].start if run_end < len(parts) else duration
            gap = max(timedelta(0), before - after)
            run = parts[index:run_end]
            total = sum(len(CompactText(part.text)) for part in run) or 1

            position = 0
            for offset, part in enumerate(run):
                part.start = after + gap * (position / total)
                position += len(CompactText(part.text))
                room = after + gap * (position / total) - part.start if offset + 1 < len(run) else before - part.start

                # A part lasts only as long as its text takes to say, so it does not stretch over silence
                speech = timedelta(seconds=EstimateSpeechSeconds(part.text))
                part.end = part.start + (min(speech, room) if room > timedelta(0) else speech)

            index = run_end

    def _fill_sparse_parts(self, parts : list[TranscriptionSegment], counts : list[PartCoverage], duration : timedelta) -> None:
        """Make room for the text a part's words missed, at the pace its matched words were spoken."""
        min_gap = timedelta(seconds=self.settings.min_gap)

        for index, (part, coverage) in enumerate(zip(parts, counts)):
            if not coverage.matched or coverage.matched >= WELL_COVERED_FRACTION * coverage.spoken:
                continue

            # Never slower than a normal speaking rate, so a pause inside the words does not stretch the part
            nominal = NominalSecondsPerChar(part.text)
            span = (part.end - part.start).total_seconds()
            pace = min(span / coverage.matched, nominal) if span > 0.0 else nominal

            # Unmatched text before the first matched word starts the part earlier, never overlapping its neighbours
            earliest = parts[index - 1].end + min_gap if index > 0 else timedelta(0)
            start = max(part.start - timedelta(seconds=coverage.leading * pace), earliest)
            if start < part.start:
                part.start = start

            latest = parts[index + 1].start - min_gap if index + 1 < len(parts) else duration
            end = min(part.start + timedelta(seconds=coverage.spoken * pace), latest)
            if end > part.end:
                part.end = end
