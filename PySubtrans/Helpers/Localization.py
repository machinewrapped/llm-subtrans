"""
Localization utilities using Python's gettext.

This module initializes a gettext translator based on the UI language from
`PySubtrans.Options` and exposes helper functions for translations.
"""
from __future__ import annotations

import gettext
import os

# Babel is optional; fall back gracefully if unavailable
try:
    from babel import Locale  # type: ignore
except Exception:  # pragma: no cover - environment without Babel
    Locale = None  # type: ignore

from PySubtrans.Helpers.Resources import GetResourcePath

_translator: gettext.NullTranslations|None = None
_domain = 'gui-subtrans'
_cached_locales: list[str] = []  # Cache for available locales

def _get_locale_dir() -> str:
    # Locale directory is resolved via resource path helper so it works in dev and bundled builds
    return GetResourcePath('locales')


def initialize_localization(language_code: str|None = None) -> None:
    """
    Initialize the gettext translation system.

    - If language_code is None, reads from Options().get('ui_language', 'en')
    - Falls back gracefully to NullTranslations when catalogs are missing
    """
    global _translator

    if language_code is None:
        language_code = 'en'  # Default to English if no language code provided

    # If a Babel Locale object is passed, convert to string code (e.g., 'en' or 'en_US')
    if Locale is not None and isinstance(language_code, Locale):  # type: ignore[arg-type]
        language_code = str(language_code)

    locale_dir = _get_locale_dir()

    try:
        _translator = gettext.translation(_domain, localedir=locale_dir, languages=[language_code])
        _translator.install()  # provides built-in _() as well
    except Exception:
        _translator = gettext.NullTranslations()
        _translator.install()


def set_language(language_code: str) -> None:
    """Switch language at runtime."""
    initialize_localization(language_code)


def _(text: str) -> str:
    """Return translated string for the active language."""
    if _translator:
        return _translator.gettext(text)
    return text


def tr(context: str, text: str) -> str:
    """Return translated string with context (pgettext)."""
    if _translator and hasattr(_translator, 'pgettext'):
        try:
            ctx_value = _translator.pgettext(context, text)  # type: ignore[attr-defined]
            # If no context-specific entry exists, pgettext returns the original text.
            # In that case, fall back to general translation if available.
            if ctx_value == text:
                general_value = _translator.gettext(text)
                if general_value != text:
                    return general_value
            return ctx_value
        except Exception:
            # On any unexpected error, return untranslated text
            return text
    # Fallback: ignore context if pgettext not available
    return _(text)


def get_available_locales() -> list[str]:
    """
    Scan the locales directory and return a list of available locale codes.
    """
    # Cache the result after first scan
    global _cached_locales
    if not _cached_locales:
        locales_dir : str = _get_locale_dir()
        languages : list[str] = []
        try:
            for name in os.listdir(locales_dir):
                path = os.path.join(locales_dir, name, 'LC_MESSAGES')
                if os.path.isdir(path):
                    languages.append(name)
        except Exception:
            # Fallback to known locales if scanning fails
            languages = ['en', 'es']
        _cached_locales = sorted(set(languages)) or ['en']
    return _cached_locales


def get_locale_display_name(locale_code: str) -> str:
    """
    Get the human-readable display name for a locale code using Babel.
    Falls back to the locale code if Babel is not available or lookup fails.
    """
    if Locale is None or not locale_code:
        return locale_code or ''
    try:
        # Normalize hyphen to underscore for Babel and parse the locale string
        loc = Locale.parse(locale_code.replace('-', '_'))  # type: ignore[attr-defined]
        return loc.display_name  # type: ignore[return-value]
    except Exception:
        # Fallback to locale code if Babel is not available or lookup fails
        return locale_code


def get_locales_with_names() -> list[tuple[str, str]]:
    """
    Get a list of (locale_code, display_name) tuples for all available locales.
    """
    locale_codes = get_available_locales()
    return [(code, get_locale_display_name(code)) for code in locale_codes]


class LocaleDisplayItem:
    """
    A simple class to represent a locale with both code and display name.
    This enables the existing dropdown system to show display names while returning codes.
    """
    def __init__(self, code: str, name: str):
        self.code : str = code
        self.name : str = name
    
    def __str__(self) -> str:
        return self.code
    
    def __eq__(self, other : object) -> bool:
        if isinstance(other, str):
            return self.code == other
        elif isinstance(other, LocaleDisplayItem):
            return self.code == other.code
        return False


def get_locale_display_items() -> list[LocaleDisplayItem]:
    """
    Get a list of LocaleDisplayItem objects for use in dropdowns.
    """
    locales_with_names = get_locales_with_names()
    return [LocaleDisplayItem(code, name) for code, name in locales_with_names]

