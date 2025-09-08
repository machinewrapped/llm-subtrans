import sys
import unittest

from PySubtitle.Helpers.Tests import log_input_expected_result, log_test_name, skip_if_debugger_attached
from PySubtitle.Helpers.Localization import (
    initialize_localization,
    set_language,
    _,
    tr,
    get_available_locales,
    get_locale_display_name,
)


class TestLocalization(unittest.TestCase):
    def test_initialize_default_english(self):
        log_test_name("Localization: initialize_default_english")
        initialize_localization("en")
        text = "Cancel"
        result = _(text)
        log_input_expected_result(text, text, result)
        self.assertEqual(result, text)

        # tr() should match _() when no context-specific entry exists
        ctx_result = tr("dialog", text)
        log_input_expected_result(("dialog", text), text, ctx_result)
        self.assertEqual(ctx_result, text)

    def test_switch_to_spanish_and_back(self):
        log_test_name("Localization: switch_to_spanish_and_back")
        # Switch to Spanish and verify a commonly-translated label
        initialize_localization("es")
        es_result = _("Cancel")
        log_input_expected_result("Cancel", "Cancelar", es_result)
        self.assertEqual(es_result, "Cancelar")

        # tr() should also use the active language
        es_ctx_result = tr("menu", "Cancel")
        log_input_expected_result(("menu", "Cancel"), "Cancelar", es_ctx_result)
        self.assertEqual(es_ctx_result, "Cancelar")

        # Now switch back to English
        set_language("en")
        en_result = _("Cancel")
        log_input_expected_result("Cancel", "Cancel", en_result)
        self.assertEqual(en_result, "Cancel")

    def test_missing_language_fallback(self):
        if skip_if_debugger_attached(self._testMethodName):
            return
            
        log_test_name("Localization: missing_language_fallback")
        initialize_localization("zz")  # non-existent locale
        # Should gracefully fall back to identity translation
        result = _("Cancel")
        log_input_expected_result("Cancel", "Cancel", result)
        self.assertEqual(result, "Cancel")

    def test_placeholder_formatting(self):
        log_test_name("Localization: placeholder_formatting")
        initialize_localization("es")
        # This msgid has a Spanish translation with the same {file} placeholder
        msgid = "Executing LoadSubtitleFile {file}"
        translated = _(msgid)
        formatted = translated.format(file="ABC.srt")
        expected_start = "Ejecutando"
        log_input_expected_result((msgid, "{file}=ABC.srt"), True, translated.startswith(expected_start))
        self.assertTrue(translated.startswith(expected_start))
        # Ensure placeholder survived translation and formats correctly
        log_input_expected_result("formatted", "Ejecutando", formatted.split()[0])
        self.assertIn("ABC.srt", formatted)

    def test_available_locales_and_display_name(self):
        log_test_name("Localization: available_locales_and_display_name")
        locales = get_available_locales()
        # Expect at least English and Spanish present in repo
        self.assertIn("en", locales)
        self.assertIn("es", locales)

        # Display name should be a non-empty string regardless of Babel availability
        name = get_locale_display_name("es")
        log_input_expected_result("get_locale_display_name('es')", True, isinstance(name, str) and len(name) > 0)
        self.assertIsInstance(name, str)
        self.assertGreater(len(name), 0)


if __name__ == '__main__':
    unittest.main()
