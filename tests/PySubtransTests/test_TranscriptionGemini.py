import os
import unittest
from collections.abc import Callable
from datetime import timedelta
from unittest.mock import Mock, patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.Providers.Provider_Gemini import (
    _is_rate_limit_error,
    _rate_limit_delay_seconds,
    _retry_hint_seconds,
    _format_retry_delay,
    map_language_code,
    parse_offset,
    parse_word_annotations,
)
import PySubtrans.Transcription.Providers.Provider_Gemini as _gemini_module
import PySubtrans.Transcription.Providers.Clients.GeminiTranscriptionClient as _gemini_client_module

GeminiTranscriptionProvider = getattr(_gemini_module, 'GeminiTranscriptionProvider', None)

class TestGeminiProvider(LoggedTestCase):
    def setUp(self):
        super().setUp()
        if GeminiTranscriptionProvider is None:
            self.skipTest("google-genai not installed")

    def test_registered(self):
        """Gemini registers when its SDK is present."""
        providers = TranscriptionProvider.get_providers()

        self.assertLoggedIn("gemini present", "Gemini", providers)

    def test_options(self):
        """Provider options describe settings for dynamic dialogs."""
        assert GeminiTranscriptionProvider is not None  # Type narrowing for PyLance
        provider = GeminiTranscriptionProvider(SettingsType())
        options = provider.GetOptions(provider.settings)

        for key in ("api_key", "model", "language", "diarize", "max_retries", "rate_limit"):
            self.assertLoggedIn(f"{key} option", key, options)

    def test_validate_requires_key(self):
        """Missing API keys fail validation with a message."""
        assert GeminiTranscriptionProvider is not None  # Type narrowing for PyLance
        with patch.dict(os.environ, {'GEMINI_API_KEY': ''}):
            provider = GeminiTranscriptionProvider(SettingsType())

            self.assertLoggedEqual("invalid without key", False, provider.ValidateSettings())

    def test_advanced_settings_match_schema(self):
        """Advanced keys must exist in the options schema, or filtering silently misses."""
        assert GeminiTranscriptionProvider is not None  # Type narrowing for PyLance
        provider = GeminiTranscriptionProvider(SettingsType({'api_key': 'k'}))
        options = provider.GetOptions(provider.settings)

        unknown = [key for key in provider.advanced_settings if key not in options]
        self.assertLoggedEqual("no stale advanced keys", [], unknown)

    def test_rate_limit_reaches_client(self):
        """Provider rate limits flow into the transcription client."""
        assert GeminiTranscriptionProvider is not None  # Type narrowing for PyLance
        provider = GeminiTranscriptionProvider(SettingsType({'api_key': 'k', 'rate_limit': 20.0}))
        client = provider.GetTranscriptionClient(SettingsType())

        self.assertLoggedEqual("client limit", 20.0, client.rate_limit)

    def test_verbatim_config(self):
        """Verbatim requests word timings, diarization and language codes."""
        assert GeminiTranscriptionProvider is not None  # Type narrowing for PyLance
        provider = GeminiTranscriptionProvider(SettingsType({'api_key': 'k'}))
        client = provider.GetTranscriptionClient(SettingsType())

        self.assertLoggedEqual("verbatim config", {"type": "verbatim", "timestamp_granularities": ["word"],
                                                   "diarization_mode": "speaker"},
                               client._transcription_config("Chinese")["mode"])
        self.assertLoggedEqual("verbatim language", ["cmn-Hans-CN"],
                               client._transcription_config("Chinese").get("language_codes"))
        self.assertLoggedEqual("diarization advertised", True, client.supports_diarization)
        self.assertLoggedEqual("timestamps advertised", True, client.supports_timestamps)

class _QuotaError(Exception):
    """Duck-typed 429 without touching the Google SDK."""
    code = 429


class TestGeminiRateLimitHelpers(LoggedTestCase):
    def test_detects_code_attribute(self):
        """Status attributes flag quota responses without SDK imports."""
        self.assertLoggedEqual("code match", True, _is_rate_limit_error(_QuotaError("slow down")))

    def test_rejects_plain_errors(self):
        """Ordinary failures never trigger backoff."""
        self.assertLoggedEqual("no retry", False, _is_rate_limit_error(ValueError("boom")))

    def test_detects_message_markers(self):
        """SDK message shapes match even without status attributes."""
        self.assertLoggedEqual("too many requests", True,
                               _is_rate_limit_error(Exception("too_many_requests")))
        self.assertLoggedEqual("error code", True,
                               _is_rate_limit_error(Exception("Error code: 429 - quota exceeded")))
        self.assertLoggedEqual("unrelated 429", False,
                               _is_rate_limit_error(Exception("room 429 is empty")))

    def test_retry_hint_parsed(self):
        """The server's retry hint sets the backoff."""
        delay = _rate_limit_delay_seconds(Exception("Please retry in 14.026600831s."), 0)

        self.assertLoggedEqual("hint delay", 14.026600831, delay)

    def test_compound_hint_parsed(self):
        """Daily-quota hints in hours and minutes parse to seconds."""
        self.assertLoggedEqual("daily quota", 11 * 3600.0 + 55 * 60.0 + 6.404103757,
                               _retry_hint_seconds(Exception("Please retry in 11h55m6.404103757s.")))
        self.assertLoggedEqual("minutes", 125.0,
                               _retry_hint_seconds(Exception("Please retry in 2m5s.")))
        self.assertLoggedEqual("no hint", None,
                               _retry_hint_seconds(Exception("quota exceeded")))

    def test_format_retry_delay(self):
        """Quota messages use human-readable waits."""
        self.assertLoggedEqual("hours", "about 11 hours", _format_retry_delay(42906.4))
        self.assertLoggedEqual("one hour", "about 1 hour", _format_retry_delay(3600.0))
        self.assertLoggedEqual("minutes", "about 14 minutes", _format_retry_delay(846.0))
        self.assertLoggedEqual("seconds", "about 14 seconds", _format_retry_delay(14.0))

    def test_fallback_backoff(self):
        """Hintless quota responses back off exponentially to a cap."""
        error = _QuotaError("quota exceeded")

        self.assertLoggedEqual("first retry", 5.0, _rate_limit_delay_seconds(error, 0))
        self.assertLoggedEqual("second retry", 10.0, _rate_limit_delay_seconds(error, 1))
        self.assertLoggedEqual("capped", 120.0, _rate_limit_delay_seconds(error, 10))
        self.assertLoggedEqual("hint clamped", 120.0,
                               _rate_limit_delay_seconds(Exception("Please retry in 500s."), 0))


class TestGeminiChunkRetry(LoggedTestCase):
    def setUp(self):
        super().setUp()
        if GeminiTranscriptionProvider is None:
            self.skipTest("google-genai not installed")

    def _client(self, max_retries : int):
        assert GeminiTranscriptionProvider is not None  # Type narrowing for PyLance
        provider = GeminiTranscriptionProvider(SettingsType({'api_key': 'k', 'max_retries': max_retries}))
        return provider.GetTranscriptionClient(SettingsType())

    def _backend(self, create_effects : list|Callable):
        """Mock the SDK backend; returns the mock client for assertions."""
        patcher = patch.object(_gemini_client_module, 'genai')
        mock_genai = patcher.start()
        self.addCleanup(patcher.stop)
        mock_client = mock_genai.Client.return_value
        uploaded = Mock(uri='file-uri')
        uploaded.name = 'file-name'
        mock_client.files.upload.return_value = uploaded
        mock_client.interactions.create.side_effect = create_effects
        return mock_client

    def _ok_interaction(self, text : str = "hello"):
        return Mock(output_text=text, steps=[])

    def test_retry_then_success(self):
        """A quota hit retries the same upload and returns the transcript."""
        client = self._client(max_retries=2)
        mock_client = self._backend([_QuotaError("Please retry in 0.01s."), self._ok_interaction()])

        result = client._transcribe_chunk(b"fake-audio", "wav", "en")

        self.assertLoggedEqual("transcript", "hello", result.text)
        self.assertLoggedEqual("single upload", 1, mock_client.files.upload.call_count)
        self.assertLoggedEqual("two attempts", 2, mock_client.interactions.create.call_count)
        mock_client.files.delete.assert_called_once_with(name='file-name')

    def test_daily_quota_fails_fast(self):
        """Hour-long quota hints fail immediately instead of sleeping it out."""
        client = self._client(max_retries=5)
        mock_client = self._backend([_QuotaError("Please retry in 11h55m6.404103757s.")])

        with patch("time.sleep") as mock_sleep:
            with self.assertRaises(SubtitleError) as raised:
                client._transcribe_chunk(b"fake-audio", "wav", "en")

        # Note: str() prefers the wrapped error, the message carries ours
        self.assertLoggedIn("quota message", "quota exceeded, retry in about 11 hours",
                             raised.exception.message)
        self.assertLoggedEqual("no retries", 1, mock_client.interactions.create.call_count)
        self.assertLoggedEqual("no sleeping", 0, mock_sleep.call_count)

    def test_exhaustion_raises(self):
        """Persistent quota responses fail loudly after max_retries."""
        client = self._client(max_retries=1)
        self._backend([_QuotaError("Please retry in 0.01s."), _QuotaError("Please retry in 0.01s.")])

        with self.assertRaises(SubtitleError) as raised:
            client._transcribe_chunk(b"fake-audio", "wav", "en")

        # Note: str() prefers the wrapped error, the message carries ours
        self.assertLoggedIn("rate limit message", "rate limit still exceeded", raised.exception.message)

    def test_non_rate_limit_fails_fast(self):
        """Ordinary failures never retry."""
        client = self._client(max_retries=3)
        mock_client = self._backend([ValueError("boom")])

        with self.assertRaises(SubtitleError) as raised:
            client._transcribe_chunk(b"fake-audio", "wav", "en")

        self.assertLoggedIn("failure message", "Gemini transcription failed", raised.exception.message)
        self.assertLoggedEqual("single attempt", 1, mock_client.interactions.create.call_count)

    def test_abort_during_backoff(self):
        """Aborts interrupt the backoff instead of sleeping it out."""
        client = self._client(max_retries=5)

        def abort_then_fail(*args, **kwargs):
            client.aborted = True
            raise _QuotaError("Please retry in 30s.")

        mock_client = self._backend(abort_then_fail)

        with self.assertRaises(SubtitleError) as raised:
            client._transcribe_chunk(b"fake-audio", "wav", "en")

        self.assertLoggedIn("abort message", "borted", raised.exception.message)
        self.assertLoggedEqual("single attempt", 1, mock_client.interactions.create.call_count)

class TestGeminiParsing(LoggedTestCase):
    def test_word_info_with_speakers(self):
        """word_info annotations parse with speaker labels and offsets."""

        def annotation(text, speaker, start, end):
            return type("Annotation", (), {
                'type': 'word_info', 'text': text, 'speaker': speaker,
                'start_offset': start, 'end_offset': end})()

        annotations = [
            annotation("就", "spk:0", "0.500s", "0.600s"),
            annotation("师", "spk:1", "2.600s", "2.700s"),
            annotation("x", "spk:1", "3s", "3s"),
            annotation("y", None, "4s", "5s"),
            type("Other", (), {'type': 'text', 'text': 'ignored'})(),
        ]
        words = parse_word_annotations(annotations)

        self.assertLoggedEqual("word count", 3, len(words))
        self.assertLoggedEqual("first speaker", "spk:0", words[0].speaker)
        self.assertLoggedEqual("second speaker", "spk:1", words[1].speaker)
        self.assertLoggedEqual("first start", timedelta(seconds=0.5), words[0].start)
        self.assertLoggedEqual("bare seconds", timedelta(seconds=4.0), words[2].start)
        self.assertLoggedEqual("unlabelled speaker", None, words[2].speaker)

    def test_offset_parsing(self):
        """Offset strings convert robustly, garbage drops out."""

        self.assertLoggedEqual("decimal", 1.2, parse_offset("1.200s"))
        self.assertLoggedEqual("bare", 3.0, parse_offset("3s"))
        self.assertLoggedEqual("none", None, parse_offset(None))
        self.assertLoggedEqual("garbage", None, parse_offset("soon"))

    def test_language_mapping(self):
        """Free-text hints map to BCP-47, codes pass through, empty auto-detects."""

        self.assertLoggedEqual("chinese", "cmn-Hans-CN", map_language_code("Chinese"))
        self.assertLoggedEqual("cantonese", "yue-Hant-HK", map_language_code("Cantonese"))
        self.assertLoggedEqual("passthrough", "en-US", map_language_code("en-US"))
        self.assertLoggedEqual("empty", None, map_language_code(""))
        self.assertLoggedEqual("none", None, map_language_code(None))
        self.assertLoggedEqual("unknown", None, map_language_code("Klingon"))

if __name__ == '__main__':
    unittest.main()
