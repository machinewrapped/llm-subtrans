from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import Enum

import regex

from PySubtrans.Helpers.Speech import SPOKEN_CHAR, IsSentenceEnd, SentenceEnds, SentenceRanges
from PySubtrans.Transcription.WordTiming import WordTiming

# Punctuation that opens what follows it, such as Spanish question marks, quotes and brackets
OPENING_CHAR = regex.compile(r'[\p{Ps}\p{Pi}¿¡]')


class WordCoverage(Enum):
    """
    How much of its transcript a provider's words can be relied on to spell.

    COMPLETE words miss at most the odd character, so they time a part by themselves.
    PARTIAL words can miss whole stretches, so a part is given room for the text they missed.
    """
    COMPLETE = 'complete'
    PARTIAL = 'partial'


@dataclass
class AlignedWord:
    """A word matched to the transcript, with the range of transcript characters it matched and how many it matched."""
    word : WordTiming
    start : int
    end : int
    matched : int


def AlignWords(text : str, words : list[WordTiming]) -> list[AlignedWord]:
    """
    Match words to the transcript they came from, character by character.

    Only spoken characters are compared, so punctuation and spacing on either side do not matter.
    Words with no matching character are left out.
    Matching keeps order on both sides, so the result is in transcript order.
    """
    offsets = [index for index, char in enumerate(text) if SPOKEN_CHAR.match(char)]
    owners = [index for index, word in enumerate(words) for char in word.text if SPOKEN_CHAR.match(char)]
    word_chars = ''.join(char for word in words for char in word.text if SPOKEN_CHAR.match(char))
    text_chars = ''.join(text[offset] for offset in offsets)

    spans : dict[int, tuple[int, int, int]] = {}
    matcher = SequenceMatcher(None, word_chars, text_chars, autojunk=False)
    for word_index, text_index, size in matcher.get_matching_blocks():
        for step in range(size):
            owner = owners[word_index + step]
            offset = offsets[text_index + step]
            first, last, count = spans.get(owner, (offset, offset, 0))
            spans[owner] = (min(first, offset), max(last, offset), count + 1)

    return [AlignedWord(words[index], first, last + 1, count) for index, (first, last, count) in sorted(spans.items())]


def CutPoints(text : str, aligned : list[AlignedWord], start : int, end : int) -> list[int]:
    """
    Divide text[start:end] among aligned words, so each word owns a slice holding its matched characters.

    Characters the words missed go to the word before them, up to the last closing punctuation in the gap.
    The rest go to the word after, so punctuation stays with the text it closes, and opening punctuation with the text it opens.
    Returns one more cut than there are words.
    """
    cuts = [start]
    for previous, word in zip(aligned, aligned[1:]):
        gap = text[previous.end:word.start]
        last_punctuation = max((index for index, char in enumerate(gap)
                                if not SPOKEN_CHAR.match(char) and not char.isspace() and not OPENING_CHAR.match(char)),
                               default=-1)
        cuts.append(previous.end + last_punctuation + 1)

    cuts.append(end)
    return cuts


def AssignToRanges(text : str, ranges : list[tuple[int, int]], aligned : list[AlignedWord]) -> list[list[WordTiming]]:
    """Give each range of the text the aligned words that start in it, respelled with their slices of it."""
    assigned : list[list[WordTiming]] = []
    for (start, end), members in zip(ranges, _words_in_ranges(ranges, aligned)):
        cuts = CutPoints(text, members, start, end)
        assigned.append([WordTiming(text=text[cuts[i]:cuts[i + 1]].strip(), start=member.word.start,
                                    end=member.word.end, speaker=member.word.speaker)
                         for i, member in enumerate(members)])

    return assigned


def TimedSentenceRanges(text : str, aligned : list[AlignedWord]) -> list[tuple[int, int]]:
    """
    Ranges of the transcript ending at sentence punctuation, full stops included.
    A full stop with a timed word starting straight after it also ends a sentence, since the words show a break the spacing does not.
    The next sentence cannot start with a lowercase letter or a digit, so decimals and names such as example.com are not divided.
    """
    word_starts = {member.start for member in aligned}
    ranges : list[tuple[int, int]] = []

    for start, end in SentenceRanges(text, SentenceEnds.ALL):
        for index in range(start, end - 1):
            if text[index] != '.' or index + 1 not in word_starts:
                continue

            following = text[index + 1]
            if following.islower() or following.isdigit():
                continue

            # Judged from the last cut as if the text broke after the full stop, so initials and dotted abbreviations still do not end a sentence
            if IsSentenceEnd(text[start:index + 1], index - start, SentenceEnds.ALL):
                ranges.append((start, index + 1))
                start = index + 1

        ranges.append((start, end))

    return ranges


def SplitAtSpeakerChanges(text : str, ranges : list[tuple[int, int]], aligned : list[AlignedWord]) -> list[tuple[int, int]]:
    """Divide ranges where the speaker of their words changes."""
    split : list[tuple[int, int]] = []
    for (start, end), members in zip(ranges, _words_in_ranges(ranges, aligned)):
        cuts = CutPoints(text, members, start, end)
        for position in range(1, len(members)):
            previous, word = members[position - 1].word, members[position].word
            if previous.speaker is not None and word.speaker is not None and previous.speaker != word.speaker:
                split.append((start, cuts[position]))
                start = cuts[position]

        split.append((start, end))

    return split


def _words_in_ranges(ranges : list[tuple[int, int]], aligned : list[AlignedWord]) -> list[list[AlignedWord]]:
    """The aligned words starting in each of a sequence of ordered ranges."""
    grouped : list[list[AlignedWord]] = []
    index = 0

    for start, end in ranges:
        members : list[AlignedWord] = []
        while index < len(aligned) and aligned[index].start < end:
            if aligned[index].start >= start:
                members.append(aligned[index])
            index += 1

        grouped.append(members)

    return grouped
