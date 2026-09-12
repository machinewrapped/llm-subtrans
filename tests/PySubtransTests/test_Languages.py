from PySubtrans.Helpers.Languages import LanguageTag, ResolveLanguage, ToBcp47Tag
from PySubtrans.Helpers.TestCases import LoggedTestCase


class TestLanguages(LoggedTestCase):
    def test_resolve_english_names(self):
        """English language names resolve case-insensitively to CLDR locales."""
        cases = {
            "Chinese": "zh",
            "chinese": "zh",
            "Traditional Chinese": "zh_Hant",
            "Cantonese": "yue",
            "Japanese": "ja",
            "Dutch": "nl",
        }
        for hint, expected in cases.items():
            locale = ResolveLanguage(hint)
            self.assertLoggedIsNotNone(f"resolved '{hint}'", locale)
            assert locale is not None
            self.assertLoggedEqual(f"locale for '{hint}'", expected, str(locale), input_value=hint)

    def test_resolve_native_and_display_names(self):
        """Languages are recognised by their own name, or by name in a display language."""
        cases = {
            "Deutsch": "de",
            "español": "es",
            "Nederlands": "nl",
            "中文": "zh",          # 中文
            "日本語": "ja",    # 日本語
            "한국어": "ko",    # 한국어
        }
        for hint, expected in cases.items():
            locale = ResolveLanguage(hint)
            self.assertLoggedIsNotNone(f"resolved {hint!a}", locale)
            assert locale is not None
            self.assertLoggedEqual(f"locale for {hint!a}", expected, str(locale), input_value=ascii(hint))

        self.assertLoggedIsNone("spanish name without display language", ResolveLanguage("chino"))
        locale = ResolveLanguage("chino", display_language="es")
        assert locale is not None
        self.assertLoggedEqual("spanish name with display language", "zh", str(locale))
        self.assertLoggedEqual("french name via tag", "ja-JP", LanguageTag("japonais", display_language="fr"))

    def test_resolve_codes(self):
        """Codes are accepted with either separator and canonicalised."""
        cases = {
            "ja": "ja",
            "pt-br": "pt_BR",
            "zh_Hant_TW": "zh_Hant_TW",
            "EN-gb": "en_GB",
            "cmn-Hans-CN": "zh_Hans_CN",
        }
        for hint, expected in cases.items():
            locale = ResolveLanguage(hint)
            self.assertLoggedIsNotNone(f"resolved '{hint}'", locale)
            assert locale is not None
            self.assertLoggedEqual(f"locale for '{hint}'", expected, str(locale), input_value=hint)

    def test_unknown_and_empty(self):
        """Unknown, empty and None hints resolve to nothing."""
        for hint in ("Klingon", "xx-YY", "", "   ", None):
            self.assertLoggedIsNone(f"hint {hint!r}", ResolveLanguage(hint), input_value=hint)
            self.assertLoggedIsNone(f"tag for {hint!r}", LanguageTag(hint), input_value=hint)

    def test_tag_fills_region(self):
        """Bare languages gain their likely region; explicit regions are kept."""
        cases = {
            "ja": "ja-JP",
            "Japanese": "ja-JP",
            "pt": "pt-BR",
            "pt-PT": "pt-PT",
            "en": "en-US",
            "en-GB": "en-GB",
            "es-419": "es-419",
            "Serbian": "sr-RS",
            "Russian": "ru-RU",
        }
        for hint, expected in cases.items():
            self.assertLoggedEqual(f"tag for '{hint}'", expected, LanguageTag(hint), input_value=hint)

    def test_tag_script_handling(self):
        """Scripts appear when explicit, or when requested for bare languages."""
        self.assertLoggedEqual("explicit script kept", "zh-Hant-TW", LanguageTag("Traditional Chinese"))
        self.assertLoggedEqual("bare zh without script", "zh-CN", LanguageTag("Chinese"))
        self.assertLoggedEqual("bare zh with script", "zh-Hans-CN", LanguageTag("Chinese", include_script=True))
        self.assertLoggedEqual("cantonese with script", "yue-Hant-HK", LanguageTag("Cantonese", include_script=True))
        self.assertLoggedEqual("latin script never implied", "en-US", LanguageTag("English", include_script=True))

        locale = ResolveLanguage("de")
        assert locale is not None
        self.assertLoggedEqual("direct formatting", "de-DE", ToBcp47Tag(locale))
