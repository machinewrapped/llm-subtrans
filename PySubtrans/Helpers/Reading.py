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
# Alphabetic uses the English limit of 20, rather than 17 for most other European languages.
# Translations tend to be wordier than authored subtitles, so the faster rate avoids over-extending them.
READING_CHARS_PER_SECOND : dict[ReadingScript, float] = {
    ReadingScript.ALPHABETIC: 20.0,
    ReadingScript.CHINESE: 9.0,
    ReadingScript.JAPANESE: 4.0,
    ReadingScript.KOREAN: 12.0,
}


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


def EstimateReadingSeconds(text : str, speed : float = 1.0) -> float:
    """
    How long a subtitle takes to read at the reading speed for its script.
    Speed scales the reading speed, so 1.0 is Netflix's limit and higher values give less time.
    """
    script = GetReadingScript(text)
    chars_per_second = READING_CHARS_PER_SECOND[script] * speed
    return CountReadingCharacters(text, script) / chars_per_second
