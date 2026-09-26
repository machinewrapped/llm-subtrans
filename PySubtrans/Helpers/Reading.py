from enum import Enum

import regex

# Characters that mark a subtitle as written in an East Asian script
KANA_CHAR = regex.compile(r'[\p{Hiragana}\p{Katakana}]')
HANGUL_CHAR = regex.compile(r'\p{Hangul}')
HAN_CHAR = regex.compile(r'\p{Han}')

# Combining marks, such as Thai vowel and tone marks, which do not add reading time
COMBINING_MARK = regex.compile(r'\p{M}')

WHITESPACE = regex.compile(r'\s+')
GRAPHEME = regex.compile(r'\X')


class ReadingScript(Enum):
    """
    The script a subtitle is read in, which sets how fast it can be read.
    Alphabetic covers Latin, Cyrillic, Thai and other scripts where reading speed is similar.
    """
    ALPHABETIC = 'alphabetic'
    CHINESE = 'chinese'
    JAPANESE = 'japanese'
    KOREAN = 'korean'


# Reading speeds in characters per second, from Netflix's adult reading speed limits.
# Alphabetic uses 17, the limit for most European languages (English allows 20).
READING_CHARS_PER_SECOND : dict[ReadingScript, float] = {
    ReadingScript.ALPHABETIC: 17.0,
    ReadingScript.CHINESE: 9.0,
    ReadingScript.JAPANESE: 4.0,
    ReadingScript.KOREAN: 12.0,
}

# The reading speed in words per minute that the rates above correspond to.
# 17 characters per second is about 180 words per minute of English.
BASELINE_WORDS_PER_MINUTE = 180


def GetReadingScript(text : str) -> ReadingScript:
    """
    The script a subtitle is read in.
    Any East Asian character decides it, since other languages rarely use them.
    Kana marks Japanese, so kanji in Japanese text are read at the Japanese rate.
    """
    if KANA_CHAR.search(text):
        return ReadingScript.JAPANESE

    if HANGUL_CHAR.search(text):
        return ReadingScript.KOREAN

    if HAN_CHAR.search(text):
        return ReadingScript.CHINESE

    return ReadingScript.ALPHABETIC


def CountReadingCharacters(text : str, script : ReadingScript) -> int:
    """
    Count the characters that take time to read, following Netflix's counting rules.
    Combining marks are not counted.
    Spaces count in alphabetic text, but not in East Asian scripts.
    """
    text = COMBINING_MARK.sub('', text)

    if script == ReadingScript.ALPHABETIC:
        text = WHITESPACE.sub(' ', text).strip()
    else:
        text = WHITESPACE.sub('', text)

    return len(GRAPHEME.findall(text))


def EstimateReadingSeconds(text : str, words_per_minute : int) -> float:
    """
    How long a subtitle takes to read at a speed in words per minute.
    Other scripts are scaled to match, so the same setting gives a natural pace in each.
    """
    script = GetReadingScript(text)
    chars_per_second = READING_CHARS_PER_SECOND[script] * words_per_minute / BASELINE_WORDS_PER_MINUTE
    return CountReadingCharacters(text, script) / chars_per_second
