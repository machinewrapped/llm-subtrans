from dataclasses import dataclass
from enum import Enum

import regex

from PySubtrans.Helpers.Speech import DEFAULT_ABBREVIATIONS, SPOKEN_CHAR, IsSentenceEnd, SentenceEnds, SentenceRanges
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
    owners : list[int] = []
    spoken : list[str] = []
    for index, word in enumerate(words):
        chars = [char for char in word.text if SPOKEN_CHAR.match(char)]
        owners.extend([index] * len(chars))
        spoken.extend(chars)

    word_chars = ''.join(spoken)
    text_chars = ''.join(text[offset] for offset in offsets)

    def longest_match(alo : int, ahi : int, blo : int, bhi : int) -> tuple[int, int, int]:
        """
        The same match as SequenceMatcher(None, word_chars, text_chars, autojunk=False).find_longest_match:
        the longest common run, then the earliest in word_chars, then the earliest in text_chars.
        Found with a suffix automaton of text_chars[blo:bhi], so it takes linear rather than quadratic time.
        """
        length, link, first_end, transitions = [0], [-1], [-1], [{}]
        last = 0
        for position in range(blo, bhi):
            char = text_chars[position]
            current = len(length)
            length.append(length[last] + 1)
            link.append(0)
            first_end.append(position)
            transitions.append({})
            state = last
            while state != -1 and char not in transitions[state]:
                transitions[state][char] = current
                state = link[state]

            if state != -1:
                target = transitions[state][char]
                if length[state] + 1 == length[target]:
                    link[current] = target
                else:
                    clone = len(length)
                    length.append(length[state] + 1)
                    link.append(link[target])
                    first_end.append(first_end[target])
                    transitions.append(dict(transitions[target]))
                    while state != -1 and transitions[state].get(char) == target:
                        transitions[state][char] = clone
                        state = link[state]
                    link[target] = clone
                    link[current] = clone

            last = current

        best_i, best_j, best_size = alo, blo, 0
        state, size = 0, 0
        for position in range(alo, ahi):
            char = word_chars[position]
            while state and char not in transitions[state]:
                state = link[state]
                size = length[state]

            state = transitions[state].get(char, 0)
            size = size + 1 if state else 0
            if size > best_size:
                best_i, best_j, best_size = position - size + 1, first_end[state] - size + 1, size

        return best_i, best_j, best_size

    # The same recursion as SequenceMatcher.get_matching_blocks, around each longest match
    blocks : list[tuple[int, int, int]] = []
    queue = [(0, len(word_chars), 0, len(text_chars))]
    while queue:
        alo, ahi, blo, bhi = queue.pop()
        i, j, size = longest_match(alo, ahi, blo, bhi)
        if size:
            blocks.append((i, j, size))
            if alo < i and blo < j:
                queue.append((alo, i, blo, j))
            if i + size < ahi and j + size < bhi:
                queue.append((i + size, ahi, j + size, bhi))

    # Blocks keep order on both sides, so each word's first match is its start and its last is its end
    spans : dict[int, list[int]] = {}
    for word_index, text_index, size in sorted(blocks):
        for owner, offset in zip(owners[word_index:word_index + size], offsets[text_index:text_index + size]):
            span = spans.get(owner)
            if span is None:
                spans[owner] = [offset, offset, 1]
            else:
                span[1] = offset
                span[2] += 1

    return [AlignedWord(words[index], first, last + 1, count) for index, (first, last, count) in spans.items()]


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


def TimedSentenceRanges(text : str, aligned : list[AlignedWord],
                        abbreviations : frozenset[str] = DEFAULT_ABBREVIATIONS) -> list[tuple[int, int]]:
    """
    Ranges of the transcript ending at sentence punctuation, full stops included.
    A full stop with a timed word starting straight after it also ends a sentence, since the words show a break the spacing does not.
    The next sentence cannot start with a lowercase letter or a digit, so decimals and names such as example.com are not divided.
    """
    word_starts = {member.start for member in aligned}
    ranges : list[tuple[int, int]] = []

    for start, end in SentenceRanges(text, SentenceEnds.ALL, abbreviations):
        for index in range(start, end - 1):
            if text[index] != '.' or index + 1 not in word_starts:
                continue

            following = text[index + 1]
            if following.islower() or following.isdigit():
                continue

            # Judged from the last cut as if the text broke after the full stop, so abbreviations and initials still do not end a sentence
            if IsSentenceEnd(text[start:index + 1], index - start, SentenceEnds.ALL, abbreviations):
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
