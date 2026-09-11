"""
Language hint resolution backed by Babel's CLDR data.

Turns free-text hints ("Chinese", "Chinois", "ja", "pt-br") into Babel
locales and BCP-47 tags, filling in likely region/script subtags so
providers that need a full tag (e.g. "ja-JP") get one. Provider-neutral:
any quirks of a specific API belong with that provider.
"""
from collections.abc import Mapping

from babel import Locale, UnknownLocaleError, localedata
from babel.core import get_global

_english_names : dict[str, str]|None = None
_endonyms : dict[str, str]|None = None
_display_names : dict[str, dict[str, str]] = {}


def _invert(languages : Mapping[str, str]) -> dict[str, str]:
    """Casefolded name -> code map from a Babel languages mapping."""
    names : dict[str, str] = {}
    for code, name in languages.items():
        if name:
            names.setdefault(str(name).casefold(), code)
    return names


def _english_language_names() -> dict[str, str]:
    """English names for every language CLDR knows, built once."""
    global _english_names
    if _english_names is None:
        _english_names = _invert(Locale('en').languages)
    return _english_names


def _language_endonyms() -> dict[str, str]:
    """
    Each language's own name for itself (中文, 日本語, Deutsch), built once
    from raw locale data as loading every Locale is slow.
    """
    global _endonyms
    if _endonyms is None:
        names : dict[str, str] = {}
        for code in localedata.locale_identifiers():
            if '_' in code:
                continue
            endonym = localedata.load(code).get('languages', {}).get(code)
            if endonym:
                names.setdefault(str(endonym).casefold(), code)
        _endonyms = names
    return _endonyms


def _display_language_names(display_language : str) -> dict[str, str]:
    """Language names as written in `display_language` (e.g. "chino" in Spanish)."""
    if display_language not in _display_names:
        try:
            _display_names[display_language] = _invert(Locale.parse(display_language.replace('-', '_')).languages)
        except (UnknownLocaleError, ValueError, TypeError):
            _display_names[display_language] = {}
    return _display_names[display_language]


def _lookup_language_name(name : str, display_language : str|None) -> str|None:
    """Find a CLDR code for a language name, trying English, the display language, then endonyms."""
    key = name.casefold()
    code = _english_language_names().get(key)
    if code is None and display_language:
        code = _display_language_names(display_language).get(key)
    if code is None:
        code = _language_endonyms().get(key)
    return code


def ResolveLanguage(hint : str|None, display_language : str|None = None) -> Locale|None:
    """
    Resolve a free-text language hint to a Babel Locale.

    Accepts language names in English ("Chinese"), in the language itself
    ("中文", "Deutsch") or in `display_language` ("chino" for "es"), or
    codes with either separator ("ja", "pt-br", "zh_Hant_TW"). Returns
    None when the hint is empty or unrecognised.
    """
    if not hint or not hint.strip():
        return None

    text = hint.strip()
    code = _lookup_language_name(text, display_language) or text.replace('-', '_')

    try:
        return Locale.parse(code)
    except (UnknownLocaleError, ValueError, TypeError):
        return None


def LanguageName(locale : Locale) -> str|None:
    """
    English CLDR name of a locale's language ("zh_Hant_TW" -> "Chinese"),
    for backends that take names rather than codes.
    """
    return Locale('en').languages.get(locale.language)


def ToBcp47Tag(locale : Locale, include_script : bool = False) -> str:
    """
    Format a locale as a BCP-47 tag, filling in the likely region when
    the locale has none (ja -> ja-JP, zh -> zh-Hans-CN).

    The script subtag is emitted when the locale carries one explicitly;
    `include_script` also emits the likely script for bare languages.
    """
    language = locale.language
    script = locale.script
    territory = locale.territory

    if territory is None or (include_script and script is None):
        likely_subtags = get_global('likely_subtags')
        likely = likely_subtags.get(str(locale)) or likely_subtags.get(language)
        if likely:
            likely_locale = Locale.parse(likely)
            if territory is None:
                territory = likely_locale.territory
            if include_script and script is None:
                script = likely_locale.script

    return '-'.join(part for part in (language, script, territory) if part)


def LanguageTag(hint : str|None, include_script : bool = False, display_language : str|None = None) -> str|None:
    """
    Resolve a hint straight to a BCP-47 tag, or None when unrecognised.
    """
    locale = ResolveLanguage(hint, display_language)
    return ToBcp47Tag(locale, include_script=include_script) if locale is not None else None
