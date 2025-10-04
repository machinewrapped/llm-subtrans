import unittest
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import skip_if_debugger_attached
from PySubtrans.Helpers.Localization import (
    initialize_localization,
    set_language,
    _,
    tr,
    get_available_locales,
    get_locale_display_name,
)

class TestLocalization(LoggedTestCase):
    def test_initialize_default_english(self):
        initialize_localization("en")
        text = "Cancel"
        result = _(text)
        self.assertLoggedEqual("default english translation", text, result)

        # tr() should match _() when no context-specific entry exists
        ctx_result = tr("dialog", text)
        self.assertLoggedEqual("context translation matches", text, ctx_result, input_value=("dialog", text))

    def test_switch_to_spanish_and_back(self):
        # Switch to Spanish and verify a commonly-translated label
        initialize_localization("es")
        es_result = _("Cancel")
        self.assertLoggedEqual("spanish translation", "Cancelar", es_result)

        # tr() should also use the active language
        es_ctx_result = tr("menu", "Cancel")
        self.assertLoggedEqual("spanish context translation", "Cancelar", es_ctx_result, input_value=("menu", "Cancel"))

        # Now switch back to English
        set_language("en")
        en_result = _("Cancel")
        self.assertLoggedEqual("english translation after switch", "Cancel", en_result)

    @skip_if_debugger_attached
    def test_missing_language_fallback(self):
        initialize_localization("zz")  # non-existent locale
        # Should gracefully fall back to identity translation
        result = _("Cancel")
        self.assertLoggedEqual("fallback translation", "Cancel", result)

    def test_placeholder_formatting(self):
        initialize_localization("es")
        # This msgid has a Spanish translation with the same {file} placeholder
        msgid = "Executing LoadSubtitleFile {file}"
        translated = _(msgid)
        formatted = translated.format(file="ABC.srt")
        expected_start = "Ejecutando"
        self.assertLoggedTrue(
            "placeholder preserved",
            translated.startswith(expected_start),
            input_value=(msgid, "{file}=ABC.srt"),
        )
        # Ensure placeholder survived translation and formats correctly
        self.assertLoggedEqual("formatted first word", "Ejecutando", formatted.split()[0], input_value=formatted)
        self.assertIn("ABC.srt", formatted)

    def test_available_locales_and_display_name(self):
        locales = get_available_locales()
        # Expect at least English and Spanish present in repo
        self.assertIn("en", locales)
        self.assertIn("es", locales)

        # Display name should be a non-empty string regardless of Babel availability
        name = get_locale_display_name("es")
        self.assertLoggedTrue(
            "locale display name present",
            isinstance(name, str) and len(name) > 0,
            input_value=name,
        )
        self.assertIsInstance(name, str)
        self.assertGreater(len(name), 0)


if __name__ == '__main__':
    unittest.main()
