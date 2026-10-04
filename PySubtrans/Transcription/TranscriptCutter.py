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
from PySubtrans.Transcription.WordAlignment import (OPENING_CHAR, AlignedWord, AlignWords, AssignToRanges, CutPoints,
                                                    SplitAtSpeakerChanges, TimedSentenceRanges, WordCoverage)
from PySubtrans.Transcription.WordTiming import WordTiming

# A spoken word lasting less than this fraction of its estimated speaking time is treated as squeezed, and not used for timing
SQUEEZED_WORD_FRACTION = 0.1

# With partial word coverage, the word timings may leave out stretches of the transcript.
# A part spanning only its timed words would then be too short to say all of its text, so it is extended.
# If the words match at least this share of the part's spoken characters, the rest is put down to the words and transcript
# writing the same speech differently (e.g. "3" and "three"), not to missing speech, and the part keeps the span of its words.
WELL_COVERED_FRACTION = 0.8


class PartCoverage(NamedTuple):
    """Spoken characters in a part: all of them, those its words matched, and those before its first matched word."""
    spoken : int
    matched : int
    leading : int


def IsSqueezed(word : WordTiming) -> bool:
    """
    Whether a spoken word lasts far less time than its text takes to say.
    An aligner that loses its place can stack the following words into a few milliseconds, so their times are not reliable.
    A word stamped with no duration at all is not squeezed: its start time is still where it was said.
    """
    if word.is_punctuation or word.start == word.end:
        return False

    return (word.end - word.start).total_seconds() < SQUEEZED_WORD_FRACTION * EstimateSpeechSeconds(word.text)


def ExtendToPunctuation(words : list[WordTiming]) -> list[WordTiming]:
    """Extend each word to the end of any punctuation-only words after it, unless they open the next utterance."""
    # Some engines return punctuation as separate words, timed to end where the utterance ends.
    # Extending the word before it lets a part closed by the punctuation end there too.
    # An opening mark such as "¿" or "“" belongs to the next utterance, and may be timed at its start.
    # Extending the word before it would stretch that word over the pause between the two.
    extended : list[WordTiming] = []
    spoken : int|None = None

    for word in words:
        if not word.is_punctuation:
            spoken = len(extended)
        elif spoken is not None and word.end > extended[spoken].end and not OPENING_CHAR.match(word.text.lstrip()):
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
        """
        Cut the transcript into timed parts, each with the words that spell it.
        A part's text is always a slice of the transcript, never rebuilt from the words.
        The words may leave out punctuation, and with partial coverage whole stretches of speech, which the transcript keeps.
        The words decide where the transcript is cut and when each part starts and ends.
        """
        text = segment.text.strip()
        duration = segment.end - segment.start

        aligned = AlignWords(text, ExtendToPunctuation(words))
        ranges = self._ranges(text, aligned)
        assigned = AssignToRanges(text, ranges, aligned)
        parts = [TranscriptionSegment(text=text[start:end].strip(), speaker=MajoritySpeaker(part_words))
                 for (start, end), part_words in zip(ranges, assigned)]

        if self.settings.word_coverage == WordCoverage.PARTIAL:
            # Squeezed words still carry speaker tags, and their starts are used to find sentence ends and speaker changes.
            # So they are kept for cutting and speaker labels above, and left out only of the words that time each part.
            timed = [word for word in aligned if not IsSqueezed(word.word)]
            assigned = AssignToRanges(text, ranges, timed)

        self._time_parts(parts, assigned, duration)
        if self.settings.word_coverage == WordCoverage.PARTIAL:
            self._fill_sparse_parts(parts, CharacterCounts(text, ranges, timed), duration)

        kept = [index for index, part in enumerate(parts) if part.text]
        return [parts[index] for index in kept], [assigned[index] for index in kept]

    def _ranges(self, text : str, aligned : list[AlignedWord]) -> list[tuple[int, int]]:
        """Where the transcript is cut into parts."""
        # Without matched words only the punctuation can divide the transcript
        if not aligned:
            return SentenceRanges(text, SentenceEnds.ALL, self.settings.abbreviations)

        sentences = TimedSentenceRanges(text, aligned, self.settings.abbreviations)
        if len(sentences) > 1 or EndsSentence(text, self.settings.abbreviations):
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
        # A part can last longer than max_line_seconds if its text takes that long to say.
        # Subtitle post-processing splits long lines by duration.
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

                # Cap the part at its estimated speaking time, so it does not cover silence in the rest of the gap
                speech = timedelta(seconds=EstimateSpeechSeconds(part.text))
                part.end = part.start + (min(speech, room) if room > timedelta(0) else speech)

            index = run_end

    def _fill_sparse_parts(self, parts : list[TranscriptionSegment], counts : list[PartCoverage], duration : timedelta) -> None:
        """Make room for the text a part's words missed, at the pace its matched words were spoken."""
        min_gap = timedelta(seconds=self.settings.min_gap)

        for index, (part, coverage) in enumerate(zip(parts, counts)):
            if not coverage.matched or coverage.matched >= WELL_COVERED_FRACTION * coverage.spoken:
                continue

            # Cap the pace at a normal speaking rate, so a pause between the matched words does not over-extend the part
            nominal = NominalSecondsPerChar(part.text)
            span = (part.end - part.start).total_seconds()
            pace = min(span / coverage.matched, nominal) if span > 0.0 else nominal

            # Unmatched text before the first matched word moves the start earlier, but not into the previous part
            earliest = parts[index - 1].end + min_gap if index > 0 else timedelta(0)
            start = max(part.start - timedelta(seconds=coverage.leading * pace), earliest)
            if start < part.start:
                part.start = start

            latest = parts[index + 1].start - min_gap if index + 1 < len(parts) else duration
            end = min(part.start + timedelta(seconds=coverage.spoken * pace), latest)
            if end > part.end:
                part.end = end
