import os
import unittest
from datetime import timedelta
from unittest.mock import Mock, patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.Providers.Clients.OpenRouterTranscriptionClient import (
    OpenRouterTranscriptionClient,
    parse_transcription_payload,
)
from PySubtrans.Transcription.Providers.Provider_OpenRouter import (
    OpenRouterTranscriptionProvider,
)


class TestOpenRouterRegistered(LoggedTestCase):
    def test_registered(self):
        """OpenRouter always registers (HTTP-only, no SDK)."""
        providers = TranscriptionProvider.get_providers()

        self.assertLoggedIn("openrouter present", "OpenRouter", providers)

    def test_rate_limit_reaches_client(self):
        """Provider rate limits flow into the transcription client."""
        provider = OpenRouterTranscriptionProvider(SettingsType({'api_key': 'k', 'rate_limit': 30.0}))
        client = provider.GetTranscriptionClient(SettingsType())

        self.assertLoggedEqual("client limit", 30.0, client.rate_limit)

    def test_rate_limit_unlimited_by_default(self):
        """No pacing unless the user opts in."""
        provider = OpenRouterTranscriptionProvider(SettingsType({'api_key': 'k'}))
        client = provider.GetTranscriptionClient(SettingsType())

        self.assertLoggedEqual("no limit", None, client.rate_limit)

    def test_progressive_options_without_key(self):
        """Only the key shows until one is set (non-empty means set up, not valid)."""
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': ''}):
            provider = OpenRouterTranscriptionProvider(SettingsType())
            options = provider.GetOptions(provider.settings)

            self.assertLoggedEqual("only api_key", ['api_key'], sorted(options.keys()))

    def test_progressive_options_with_key(self):
        """A non-empty key unlocks the full schema."""
        provider = OpenRouterTranscriptionProvider(SettingsType({'api_key': 'k'}))

        with patch('httpx.Client') as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = Mock(
                is_error=False, status_code=200, text="")
            options = provider.GetOptions(provider.settings)

        for key in ('api_key', 'model', 'language', 'diarize', 'request_timeout', 'rate_limit'):
            self.assertLoggedIn(f"{key} option", key, options)

    def test_language_resolves_to_iso_code(self):
        """Whisper-compatible endpoints get ISO 639-1 codes."""
        provider = OpenRouterTranscriptionProvider(SettingsType({'api_key': 'k'}))

        self.assertLoggedEqual("english name", "zh", provider.ResolveLanguageCode("Chinese"))
        self.assertLoggedEqual("regional tag", "pt", provider.ResolveLanguageCode("pt-BR"))
        self.assertLoggedIsNone("no hint", provider.ResolveLanguageCode(None))

    def test_progressive_options_inherited_key(self):
        """Keys inherited from the environment count as set up."""
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'env-key'}):
            provider = OpenRouterTranscriptionProvider(SettingsType())

            with patch('httpx.Client') as mock_client:
                mock_client.return_value.__enter__.return_value.get.return_value = Mock(
                    is_error=False, status_code=200, text="")
                options = provider.GetOptions(provider.settings)

            self.assertLoggedIn("model option", 'model', options)

    def test_advanced_settings_match_schema(self):
        """Advanced keys must exist in the options schema, or filtering silently misses."""
        provider = OpenRouterTranscriptionProvider(SettingsType({'api_key': 'k'}))

        with patch('httpx.Client') as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = Mock(
                is_error=False, status_code=200, text="")
            options = provider.GetOptions(provider.settings)

        unknown = [key for key in provider.advanced_settings if key not in options]
        self.assertLoggedEqual("no stale advanced keys", [], unknown)

class TestOpenRouterParsing(LoggedTestCase):
    def test_verbose_words_with_speakers(self):
        """Word timings and speaker labels parse from verbose responses."""

        payload = {
            'text': 'hello world',
            'language': 'en',
            'words': [
                {'word': 'hello', 'start': 0.5, 'end': 0.9, 'speaker': 0},
                {'word': 'world', 'start': 1.0, 'end': 1.4, 'speaker': 1},
            ],
        }
        text, language, _parts, words = parse_transcription_payload(payload)

        self.assertLoggedEqual("text", "hello world", text)
        self.assertLoggedEqual("language", "en", language)
        self.assertLoggedEqual("word count", 2, len(words))
        self.assertLoggedEqual("first speaker", "0", words[0].speaker)
        self.assertLoggedEqual("second speaker", "1", words[1].speaker)


    def test_segments_without_words(self):
        """Segments parse when word timings are absent."""

        payload = {
            'text': 'first second',
            'segments': [
                {'text': 'first', 'start': 0.0, 'end': 2.0, 'speaker': 'A'},
                {'text': 'second', 'start': 2.5, 'end': 4.0},
            ],
        }
        _text, _language, parts, words = parse_transcription_payload(payload)

        self.assertLoggedEqual("part count", 2, len(parts))
        self.assertLoggedEqual("part speaker", "A", parts[0].speaker)
        self.assertLoggedEqual("no speaker", None, parts[1].speaker)
        self.assertLoggedEqual("word count", 0, len(words))

    def test_malformed_entries_skipped(self):
        """Invalid segments and words never produce degenerate lines."""

        payload = {
            'text': 'ok',
            'segments': [{'text': '', 'start': 0.0, 'end': 1.0}, 'junk', {'text': 'ok', 'start': 5.0, 'end': 4.0}],
            'words': [{'word': 'ok', 'start': 'soon', 'end': 1.0}],
        }
        text, _language, parts, words = parse_transcription_payload(payload)

        self.assertLoggedEqual("text", "ok", text)
        self.assertLoggedEqual("part count", 0, len(parts))
        self.assertLoggedEqual("word count", 0, len(words))

    def test_missing_optional_fields_skipped_silently(self):
        """Absent no_speech_prob and timings parse without raising anything."""
        payload = {
            'text': 'hi',
            'segments': [{'text': 'hi', 'start': 0.0, 'end': 1.0}],
        }
        text, _language, parts, _words = parse_transcription_payload(payload)

        self.assertLoggedEqual("text", "hi", text)
        self.assertLoggedEqual("part count", 1, len(parts))
        self.assertLoggedEqual("no confidence", None, parts[0].confidence)

class TestOpenRouterCatalog(LoggedTestCase):
    def _provider(self):
        return OpenRouterTranscriptionProvider(SettingsType({
            'server_address': 'http://127.0.0.1:9/v1', 'api_key': 'test-key',
        }))

    def _mock_get(self, text : str, is_error : bool = False):
        response = Mock()
        response.is_error = is_error
        response.status_code = 500 if is_error else 200
        response.text = text
        return response

    def test_empty_catalog_body_falls_back(self):
        """Empty catalog responses degrade without raising anything."""
        provider = self._provider()

        with patch('httpx.Client') as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = self._mock_get("")
            models = provider.GetAvailableModels()

        self.assertLoggedIn("fallback model", "openai/whisper-large-v3", models)

    def test_malformed_catalog_falls_back(self):
        """Non-JSON catalog responses degrade without raising anything."""
        provider = self._provider()

        with patch('httpx.Client') as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = self._mock_get("not json{")
            models = provider.GetAvailableModels()

        self.assertLoggedIn("fallback model", "openai/whisper-large-v3", models)

    def test_html_catalog_body_falls_back(self):
        """HTML error pages degrade without raising anything."""
        provider = self._provider()

        with patch('httpx.Client') as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = self._mock_get(
                "<!DOCTYPE html><html>Bad Gateway</html>")
            models = provider.GetAvailableModels()

        self.assertLoggedIn("fallback model", "openai/whisper-large-v3", models)

    def test_unreachable_catalog_falls_back(self):
        """Unreachable catalogs degrade without raising anything."""
        provider = self._provider()

        with patch('httpx.Client', side_effect=Exception("unreachable")):
            models = provider.GetAvailableModels()

        self.assertLoggedIn("fallback model", "openai/whisper-large-v3", models)

class TestOpenRouterClient(LoggedTestCase):
    def _client(self, model : str = "openai/whisper-large-v3", diarize : bool = False):
        return OpenRouterTranscriptionClient(SettingsType({
            'server_address': 'http://127.0.0.1:9/v1', 'api_key': 'test-key',
            'model': model, 'diarize': diarize,
        }))

    def test_usage_cost_and_duration_parsed(self):
        """Usage blocks attach duration and billed cost to the result."""
        client = OpenRouterTranscriptionClient(SettingsType({
            'server_address': 'http://127.0.0.1:9/v1', 'api_key': 'test-key',
            'model': 'openai/whisper-large-v3',
        }))

        with patch('httpx.Client') as mock_client:
            mock_response = mock_client.return_value.__enter__.return_value.post.return_value
            mock_response.status_code = 200
            mock_response.is_error = False
            mock_response.text = ('{"text": "hi", "language": "en", "duration": 9.2,'
                                  ' "usage": {"cost": 0.000508, "seconds": 9.2}}')
            result = client.TranscribeChunk(b"fake-audio", "wav")

        self.assertLoggedEqual("duration", timedelta(seconds=9.2), result.duration)
        self.assertLoggedEqual("cost", 0.000508, result.cost)

    def test_no_speech_prob_maps_to_confidence(self):
        """no_speech_prob surfaces as segment confidence for review."""

        payload = {
            'text': 'hmm',
            'segments': [{'text': 'hmm', 'start': 1.0, 'end': 2.0, 'no_speech_prob': 0.85}],
        }
        _text, _language, parts, _words = parse_transcription_payload(payload)

        self.assertLoggedEqual("part count", 1, len(parts))
        assert parts[0].confidence is not None  # Type narrowing for PyLance
        self.assertLoggedGreater("low confidence", 0.2, parts[0].confidence)
        self.assertLoggedGreater("below threshold", 0.4, parts[0].confidence)

    def test_client_capability_flags(self):
        """OpenRouter negotiates timestamps; diarization follows the toggle."""
        timed = self._client()
        silent = self._client(diarize=False)

        self.assertLoggedEqual("timestamps negotiated", True, timed.supports_timestamps)
        self.assertLoggedEqual("no diarization by default", False, silent.supports_diarization)

        diarized = self._client(model="microsoft/mai-transcribe-2", diarize=True)
        self.assertLoggedEqual("diarization requested", True, diarized.supports_diarization)

    def test_html_transcription_body_readable_error(self):
        """HTML error pages surface as readable errors, not decode failures."""
        client = self._client()

        with patch('httpx.Client') as mock_client:
            mock_response = mock_client.return_value.__enter__.return_value.post.return_value
            mock_response.status_code = 200
            mock_response.is_error = False
            mock_response.text = "<!DOCTYPE html><html>Bad Gateway</html>"
            with self.assertRaisesRegex(SubtitleError, "non-JSON response"):
                client.TranscribeChunk(b"fake-audio", "wav")

    def test_empty_text_returned_not_raised(self):
        """Empty transcripts return quietly for the coordinator to skip."""
        client = self._client()

        with patch('httpx.Client') as mock_client:
            mock_response = mock_client.return_value.__enter__.return_value.post.return_value
            mock_response.status_code = 200
            mock_response.is_error = False
            mock_response.text = '{"text": "", "usage": {"cost": 0.0001}}'
            result = client.TranscribeChunk(b"fake-audio", "wav")

        self.assertLoggedEqual("empty text", "", result.text)

    def test_verbose_rejection_fails_fast(self):
        """Providers rejecting verbose output fail fast instead of billing twice."""
        client = self._client()

        with patch('httpx.Client') as mock_client:
            post = mock_client.return_value.__enter__.return_value.post
            verbose = Mock()
            verbose.status_code = 400
            verbose.is_error = True
            verbose.text = '{"error": "verbose_json not supported"}'
            post.side_effect = [verbose]
            with self.assertRaisesRegex(SubtitleError, "does not support"):
                client.TranscribeChunk(b"fake-audio", "wav")

        self.assertLoggedEqual("single request", 1, post.call_count)

    def test_diarize_mapping_azure(self):
        """Diarize maps onto Azure options for Microsoft models."""
        client = self._client(model="microsoft/mai-transcribe-2", diarize=True)

        options = client._diarize_options()

        self.assertLoggedIn("azure options", "azure", options)

    def test_diarize_mapping_deepgram(self):
        """Diarize maps onto Deepgram options."""
        client = self._client(model="deepgram/nova-3", diarize=True)

        options = client._diarize_options()

        self.assertLoggedIn("deepgram options", "deepgram", options)

    def test_diarize_unmapped_model(self):
        """Unmapped models request without diarization options."""
        client = self._client(model="openai/whisper-large-v3", diarize=True)

        options = client._diarize_options()

        self.assertLoggedEqual("empty options", {}, options)

if __name__ == '__main__':
    unittest.main()
