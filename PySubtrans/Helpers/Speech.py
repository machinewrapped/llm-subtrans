from enum import Enum

import regex

# Sentence-ending punctuation across CJK and latin scripts
SENTENCE_END_CHARS = frozenset('。！？!?\n…')

# A character that is spoken, rather than punctuation, a symbol or spacing
SPOKEN_CHAR = regex.compile(r'[^\p{P}\p{S}\s]')

# Characters that may close a sentence after its end punctuation, such as quotes and brackets
CLOSING_CHARS = regex.compile(r'[\p{Pe}\p{Pf}"\'\s]+$')

# Punctuation that may open a word, such as quotes, brackets and Spanish marks
OPENING_PUNCTUATION = '"\'([{¿¡“‘«'

# Scripts written with one character per syllable, which take longer to say per character
SYLLABIC_CHAR = regex.compile(r'[\p{Han}\p{Hiragana}\p{Katakana}\p{Hangul}]')

# Speaking rates for estimating how long text takes to say.
# The syllabic rate is the median of OpenRouter parts for Cantonese dialogue.
SYLLABIC_SECONDS_PER_CHAR = 0.2
OTHER_SECONDS_PER_CHAR = 0.07
MIN_SPEECH_SECONDS = 0.3

# Titles that end with a full stop mid-sentence, as a comma-separated setting.
# Titles that come before a name are listed, since suffixes such as Jr. can end a sentence.
# Sr. is listed as the Spanish title, which is far more common than the English suffix.
STANDARD_ABBREVIATIONS = "Mr,Mrs,Ms,Dr,Mme,Mlle,Sr,Sra,Srta"


class SentenceEnds(Enum):
    """
    Which punctuation ends a sentence.

    STRONG is question and exclamation marks, CJK full stops, ellipses and line breaks.
    ALL adds full stops, other than after initials, dotted abbreviations or listed abbreviations.
    """
    STRONG = 'strong'
    ALL = 'all'


def ParseAbbreviations(abbreviations : str|list[str]) -> frozenset[str]:
    """Abbreviations from a comma-separated setting or a list, without their full stops."""
    if isinstance(abbreviations, str):
        abbreviations = abbreviations.split(',')

    return frozenset(word.strip().rstrip('.') for word in abbreviations if word.strip().rstrip('.'))


DEFAULT_ABBREVIATIONS = ParseAbbreviations(STANDARD_ABBREVIATIONS)


def NominalSecondsPerChar(text : str) -> float:
    """The normal time to say one spoken character of the text, from its script."""
    syllabic = len(SYLLABIC_CHAR.findall(text))
    other = sum(1 for char in text if char.isalnum()) - syllabic
    if syllabic + other == 0:
        return SYLLABIC_SECONDS_PER_CHAR

    return (syllabic * SYLLABIC_SECONDS_PER_CHAR + other * OTHER_SECONDS_PER_CHAR) / (syllabic + other)


def EstimateSpeechSeconds(text : str) -> float:
    """Roughly how long text takes to say, from its character count and script."""
    syllabic = len(SYLLABIC_CHAR.findall(text))
    other = sum(1 for char in text if char.isalnum()) - syllabic
    return max(MIN_SPEECH_SECONDS, syllabic * SYLLABIC_SECONDS_PER_CHAR + other * OTHER_SECONDS_PER_CHAR)


def IsSpoken(text : str) -> bool:
    """Whether the text has anything to say, rather than only punctuation, symbols and spacing."""
    return bool(SPOKEN_CHAR.search(text))


def EndsSentence(text : str, abbreviations : frozenset[str] = DEFAULT_ABBREVIATIONS) -> bool:
    """Whether a word, with any punctuation attached, ends a sentence, full stops included."""
    # Closing quotes and brackets can follow the sentence end
    text = CLOSING_CHARS.sub('', text)
    return bool(text) and IsSentenceEnd(text, len(text) - 1, SentenceEnds.ALL, abbreviations)


def IsSentenceEnd(text : str, index : int, ends : SentenceEnds = SentenceEnds.STRONG,
                  abbreviations : frozenset[str] = DEFAULT_ABBREVIATIONS) -> bool:
    """
    Whether the character at index ends a sentence.
    Abbreviations match only as written, without their full stops, as ParseAbbreviations gives them.
    """
    if text[index] in SENTENCE_END_CHARS:
        return True

    if ends != SentenceEnds.ALL or text[index] != '.':
        return False

    # A full stop counts only where the text breaks after it, so decimals do not
    if index + 1 < len(text) and not CLOSING_CHARS.match(text[index + 1]):
        return False

    # Full stops typed as an ellipsis end a sentence, like …
    if text.endswith('...', 0, index + 1):
        return True

    return not _is_abbreviation(text, index, abbreviations)


def _is_abbreviation(text : str, index : int, abbreviations : frozenset[str]) -> bool:
    """Whether the full stop at index closes initials, a dotted abbreviation or a listed abbreviation, rather than a sentence."""
    start = index
    while start > 0 and not text[start - 1].isspace():
        start -= 1

    word = text[start:index]
    letters = word.lstrip(OPENING_PUNCTUATION)

    # Initials and dotted abbreviations, such as J. or U.S.A.
    # A single syllabic character is a whole word, such as Korean 중., not an initial
    is_initial = len(letters) == 1 and letters.isalpha() and not SYLLABIC_CHAR.match(letters)
    return is_initial or '.' in letters or letters in abbreviations


def SentenceRanges(text : str, ends : SentenceEnds = SentenceEnds.STRONG,
                   abbreviations : frozenset[str] = DEFAULT_ABBREVIATIONS) -> list[tuple[int, int]]:
    """Ranges of the text ending at sentence punctuation, with any closing quotes or brackets."""
    ranges : list[tuple[int, int]] = []
    start = 0
    index = 0

    while index < len(text):
        if IsSentenceEnd(text, index, ends, abbreviations):
            end = index + 1
            while end < len(text) and (IsSentenceEnd(text, end, ends, abbreviations) or CLOSING_CHARS.match(text[end])):
                end += 1
            ranges.append((start, end))
            start = index = end
        else:
            index += 1

    if start < len(text):
        ranges.append((start, len(text)))

    return ranges
