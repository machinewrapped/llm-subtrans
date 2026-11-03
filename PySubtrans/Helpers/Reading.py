import unicodedata

import regex

from PySubtrans.Helpers.Languages import ResolveLanguage

# Adult reading speed limits in characters per second, from Netflix's Timed Text Style Guides.
# Languages without an entry use DEFAULT_CHARS_PER_SECOND, the limit for most languages.
# Where a guide gives a separate limit for SDH, that limit is used.
# Professional subtitles are condensed to meet the lower limit, but LLM translations are closer to verbatim, like SDH.
# This applies to Japanese (4 for subtitles, 7 for SDH), Afrikaans and Zulu (17 and 20).
READING_CHARS_PER_SECOND : dict[str, float] = {
    'en': 20.0,
    'ar': 20.0,
    'af': 20.0,
    'zu': 20.0,
    'bn': 22.0,
    'hi': 22.0,
    'kn': 22.0,
    'ml': 22.0,
    'mr': 22.0,
    'ta': 22.0,
    'te': 22.0,
    'ko': 12.0,
    'zh': 9.0,
    'ja': 7.0,
}
DEFAULT_CHARS_PER_SECOND = 17.0

# Languages where half-width characters, such as Latin letters, spaces and punctuation, count as half a character
CHARACTER_BASED_LANGUAGES = frozenset({ 'ja', 'ko', 'zh' })
HALF_WIDTH_CHARACTER = 0.5

# Scripts that identify a language when the target language is unknown, checked in order.
# Kana marks Japanese, so kanji in Japanese text are read at the Japanese rate.
SCRIPT_LANGUAGES : list[tuple[regex.Pattern[str], str]] = [
    (regex.compile(r'[\p{Hiragana}\p{Katakana}]'), 'ja'),
    (regex.compile(r'\p{Hangul}'), 'ko'),
    (regex.compile(r'\p{Han}'), 'zh'),
    (regex.compile(r'\p{Devanagari}'), 'hi'),
    (regex.compile(r'\p{Bengali}'), 'bn'),
    (regex.compile(r'\p{Tamil}'), 'ta'),
    (regex.compile(r'\p{Telugu}'), 'te'),
    (regex.compile(r'\p{Kannada}'), 'kn'),
    (regex.compile(r'\p{Malayalam}'), 'ml'),
    (regex.compile(r'\p{Arabic}'), 'ar'),
]

# Thai tone marks and upper and lower vowels, which Netflix does not count
THAI_COMPOSITE_MARK = regex.compile(r'[ัิ-ฺ็-๎]')

# Runs of whitespace other than the full-width space, which counts as a character in its own right
COLLAPSIBLE_WHITESPACE = regex.compile(r'[^\S　]+')

# A qualifier on a language name, such as "(Simplified)" or "(Canada)"
LANGUAGE_QUALIFIER = regex.compile(r'\s*\([^)]*\)')


def GetReadingLanguage(target_language : str|None) -> str|None:
    """
    The language code whose reading speed applies to a target language, or None when it is unrecognised.
    Qualified names such as "Chinese (Simplified)" resolve by their base language, since variants share a reading speed.
    """
    locale = ResolveLanguage(target_language)
    if locale is None and target_language:
        locale = ResolveLanguage(LANGUAGE_QUALIFIER.sub('', target_language))

    return locale.language if locale is not None else None


def DetectReadingLanguage(text : str) -> str|None:
    """
    Identify a language with its own reading speed from the script of the text, or None for the default speed.
    """
    for pattern, language in SCRIPT_LANGUAGES:
        if pattern.search(text):
            return language

    return None


def GetReadingSpeed(language : str|None) -> float:
    """
    Netflix's adult reading speed limit for a language, in characters per second.
    """
    return READING_CHARS_PER_SECOND.get(language or '', DEFAULT_CHARS_PER_SECOND)


def CountReadingCharacters(text : str, language : str|None) -> float:
    """
    Count characters the way Netflix measures reading speed.
    Spaces and punctuation count, with runs of whitespace and line breaks counted as one space.
    Half-width characters count as half a character in Chinese, Japanese and Korean.
    Thai tone marks and upper and lower vowels are not counted.
    """
    text = unicodedata.normalize('NFC', text)
    text = THAI_COMPOSITE_MARK.sub('', text)
    text = COLLAPSIBLE_WHITESPACE.sub(' ', text).strip()

    if language not in CHARACTER_BASED_LANGUAGES:
        return float(len(text))

    return sum(1.0 if unicodedata.east_asian_width(char) in ('F', 'W', 'A') else HALF_WIDTH_CHARACTER for char in text)


def EstimateReadingSeconds(text : str, language : str|None = None, speed : float = 1.0) -> float:
    """
    How long a subtitle takes to read at Netflix's reading speed limit for its language.
    The language is detected from the script of the text when it is not given.
    Speed scales the reading speed, so higher values give less time.
    """
    language = language or DetectReadingLanguage(text)
    chars_per_second = GetReadingSpeed(language) * speed
    return CountReadingCharacters(text, language) / chars_per_second
