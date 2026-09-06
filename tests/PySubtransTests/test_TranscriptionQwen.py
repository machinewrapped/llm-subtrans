import unittest
from datetime import timedelta

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.SettingsType import SettingsType
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.Providers.Provider_QwenLocal import parse_qwen_result
import PySubtrans.Transcription.Providers.Provider_QwenLocal as _qwen_module

QwenLocalProvider = getattr(_qwen_module, 'QwenLocalProvider', None)

class TestQwenLocalProvider(LoggedTestCase):
    def setUp(self):
        super().setUp()
        if QwenLocalProvider is None:
            self.skipTest("qwen-asr not installed")

    def test_registered(self):
        """Qwen Local registers when its SDK is present."""
        providers = TranscriptionProvider.get_providers()

        self.assertLoggedIn("qwen present", "Qwen Local", providers)

    def test_options(self):
        """Provider options describe settings for dynamic dialogs."""
        assert QwenLocalProvider is not None  # Type narrowing for PyLance
        provider = QwenLocalProvider(SettingsType())
        options = provider.GetOptions(provider.settings)

        for key in ("model", "language", "device", "aligner_model", "max_new_tokens", "rate_limit"):
            self.assertLoggedIn(f"{key} option", key, options)
        self.assertLoggedIn("checkpoint", "Qwen/Qwen3-ASR-1.7B", provider.GetAvailableModels())

    def test_advanced_settings_match_schema(self):
        """Advanced keys must exist in the options schema, or filtering silently misses."""
        assert QwenLocalProvider is not None  # Type narrowing for PyLance
        provider = QwenLocalProvider(SettingsType())
        options = provider.GetOptions(provider.settings)

        unknown = [key for key in provider.advanced_settings if key not in options]
        self.assertLoggedEqual("no stale advanced keys", [], unknown)

    def test_validate_needs_no_key(self):
        """Local inference validates without credentials."""
        assert QwenLocalProvider is not None  # Type narrowing for PyLance
        provider = QwenLocalProvider(SettingsType())

        self.assertLoggedEqual("valid by default", True, provider.ValidateSettings())

    def test_client_construction(self):
        """Client builds without touching torch (lazy model load)."""
        assert QwenLocalProvider is not None  # Type narrowing for PyLance
        provider = QwenLocalProvider(SettingsType())
        client = provider.GetTranscriptionClient(SettingsType())

        self.assertLoggedEqual("client type", "QwenLocalClient", type(client).__name__)
        self.assertLoggedEqual("timestamps advertised", True, client.supports_timestamps)

class TestQwenResultParsing(LoggedTestCase):
    def test_parse_timestamps(self):
        """qwen-asr results extract text, language and word timings."""
        unit = type("Unit", (), {'text': 'hello', 'start_time': 0.5, 'end_time': 0.9})()
        result = type("Result", (), {'text': 'hello', 'language': 'Chinese', 'time_stamps': [unit]})()
        text, language, words = parse_qwen_result(result)

        self.assertLoggedEqual("text", "hello", text)
        self.assertLoggedEqual("language", "Chinese", language)
        self.assertLoggedEqual("word count", 1, len(words))
        self.assertLoggedEqual("word start", timedelta(seconds=0.5), words[0].start)

    def test_parse_flat_result(self):
        """Results without timestamps parse to text-only."""
        result = type("Result", (), {'text': 'hi', 'language': None, 'time_stamps': None})()
        text, language, words = parse_qwen_result(result)

        self.assertLoggedEqual("text", "hi", text)
        self.assertLoggedEqual("language", None, language)
        self.assertLoggedEqual("word count", 0, len(words))

if __name__ == '__main__':
    unittest.main()
