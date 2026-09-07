import json
import os
import unittest
from datetime import timedelta
from unittest.mock import Mock, patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.Providers.Provider_Muse import (
    MuseTranscriptionProvider,
)
from PySubtrans.Transcription.Providers.Clients.MuseTranscriptionClient import (
    parse_muse_payload,
)


class TestMuseRegistered(LoggedTestCase):
    def test_registered(self):
        """Muse always registers (HTTP-only, no SDK)."""
        providers = TranscriptionProvider.get_providers()

        self.assertLoggedIn("muse present", "Muse", providers)

    def test_rate_limit_reaches_client(self):
        """Provider rate limits flow into the transcription client."""
        provider = MuseTranscriptionProvider(SettingsType({'api_key': 'k', 'rate_limit': 30.0}))
        client = provider.GetTranscriptionClient(SettingsType())

        self.assertLoggedEqual("client limit", 30.0, client.rate_limit)

    def test_rate_limit_unlimited_by_default(self):
        """No pacing unless the user opts in."""
        provider = MuseTranscriptionProvider(SettingsType({'api_key': 'k'}))
        client = provider.GetTranscriptionClient(SettingsType())

        self.assertLoggedEqual("no limit", None, client.rate_limit)

    def test_advanced_settings_match_schema(self):
        """Advanced keys must exist in the options schema, or filtering silently misses."""
        provider = MuseTranscriptionProvider(SettingsType({'api_key': 'k'}))
        options = provider.GetOptions(provider.settings)

        unknown = [key for key in provider.advanced_settings if key not in options]
        self.assertLoggedEqual("no stale advanced keys", [], unknown)

    def test_information_exposed(self):
        """GetInformation() exposes each provider's information text (no dead blocks)."""
        seen = 0
        for name, provider_class in TranscriptionProvider.get_providers().items():
            with self.subTest(provider=name):
                provider = provider_class(SettingsType({'api_key': 'k'}))
                expected = getattr(provider, 'information', None)
                self.assertLoggedEqual(f"{name} info matches attribute", expected, provider.GetInformation())
                if expected:
                    seen += 1
        self.assertLoggedGreater("providers with info text", seen, 0)

class TestMuseTranscription(LoggedTestCase):
    def _provider(self, diarize : bool = False):
        return MuseTranscriptionProvider(SettingsType({'api_key': 'test-key', 'diarize': diarize}))

    def test_turns_parsed_with_speakers(self):
        """Turns carry speaker labels with start and end offsets in milliseconds."""

        payload = {
            'transcript': 'How is the weather? It is raining.',
            'audioDurationMs': 8000,
            'turns': [
                {'speaker': 'A', 'transcript': 'How is the weather?', 'startMs': 1520, 'endMs': 2460},
                {'speaker': 'B', 'transcript': 'It is raining.', 'startMs': 5900, 'endMs': 8000},
            ],
        }
        text, parts = parse_muse_payload(payload)

        self.assertLoggedEqual("text", "How is the weather? It is raining.", text)
        self.assertLoggedEqual("part count", 2, len(parts))
        self.assertLoggedEqual("first speaker", "A", parts[0].speaker)
        self.assertLoggedEqual("first start", timedelta(seconds=1.52), parts[0].start)
        self.assertLoggedEqual("first end honoured", timedelta(seconds=2.46), parts[0].end)
        self.assertLoggedEqual("last end bounded", timedelta(seconds=8.0), parts[1].end)

    def test_missing_end_falls_back_to_next_start(self):
        """A turn without endMs runs until the next turn starts."""

        payload = {
            'transcript': 'hi yo',
            'turns': [
                {'speaker': 'A', 'transcript': 'hi', 'startMs': 0},
                {'speaker': 'B', 'transcript': 'yo', 'startMs': 2000, 'endMs': 3000},
            ],
        }
        _text, parts = parse_muse_payload(payload)

        self.assertLoggedEqual("part count", 2, len(parts))
        self.assertLoggedEqual("chained end", timedelta(seconds=2.0), parts[0].end)
    def test_gaps_do_not_stretch_turns(self):
        """A turn before a long silence keeps its own end offset."""

        payload = {
            'transcript': 'x y',
            'turns': [
                {'speaker': 'A', 'transcript': 'x', 'startMs': 23740, 'endMs': 29100},
                {'speaker': 'A', 'transcript': 'y', 'startMs': 49100, 'endMs': 52700},
            ],
        }
        _text, parts = parse_muse_payload(payload)

        self.assertLoggedEqual("part count", 2, len(parts))
        self.assertLoggedEqual("true end", timedelta(seconds=29.1), parts[0].end)

    def test_speakers_stripped_unless_opted_in(self):
        """Speaker labels are dropped when diarization is not requested."""

        payload = {
            'transcript': 'hello world',
            'turns': [
                {'speaker': 'A', 'transcript': 'hello world', 'startMs': 0, 'endMs': 1000},
            ],
        }
        text, parts = parse_muse_payload(payload, include_speakers=False)

        self.assertLoggedEqual("text", "hello world", text)
        self.assertLoggedEqual("part count", 1, len(parts))
        self.assertLoggedEqual("no speaker", None, parts[0].speaker)

    def test_malformed_turns_skipped(self):
        """Empty turns and missing offsets never produce degenerate lines."""

        payload = {
            'transcript': 'ok',
            'turns': ['junk', {'transcript': '', 'startMs': 0.0}, {'transcript': 'ok'}],
        }
        text, parts = parse_muse_payload(payload, chunk_seconds=5.0)

        self.assertLoggedEqual("text", "ok", text)
        self.assertLoggedEqual("part count", 0, len(parts))

    def test_diarize_request_fields(self):
        """Diarize posts DIARIZATION mode with a JSON request part."""
        provider = self._provider(diarize=True)
        client = provider.GetTranscriptionClient(SettingsType())

        with patch('httpx.Client') as mock_client:
            post = mock_client.return_value.__enter__.return_value.post
            mock_response = Mock()
            mock_response.is_error = False
            mock_response.status_code = 200
            mock_response.text = ('{"transcript": "hi", "audioDurationMs": 2000, "turns": ['
                                  '{"speaker": "A", "transcript": "hi", "startMs": 0}]}')
            post.return_value = mock_response
            result = client.TranscribeChunk(b"fake-audio", "wav", "en")

        sent = post.call_args.kwargs['files']
        request = json.loads(sent['request'][1])
        self.assertLoggedEqual("diarize mode", "DIARIZATION", request['mode'])
        self.assertLoggedEqual("model", "muse-voice-transcribe-1.0", request['model'])
        self.assertLoggedEqual("language hint", ["en"], request['languageBias'])
        self.assertLoggedEqual("part count", 1, len(result.parts))
        self.assertLoggedEqual("part speaker", "A", result.parts[0].speaker)

    def test_plain_request_fields(self):
        """DIARIZATION is always requested; speakers stripped unless opted in."""
        provider = self._provider(diarize=False)
        client = provider.GetTranscriptionClient(SettingsType())

        with patch('httpx.Client') as mock_client:
            post = mock_client.return_value.__enter__.return_value.post
            mock_response = Mock()
            mock_response.is_error = False
            mock_response.status_code = 200
            mock_response.text = ('{"transcript": "hi", "audioDurationMs": 2000, "turns": ['
                                  '{"speaker": "A", "transcript": "hi", "startMs": 0, "endMs": 1000}]}')
            post.return_value = mock_response
            result = client.TranscribeChunk(b"fake-audio", "wav", None)

        sent = post.call_args.kwargs['files']
        request = json.loads(sent['request'][1])
        self.assertLoggedEqual("always diarized", "DIARIZATION", request['mode'])
        self.assertLoggedEqual("no bias key", False, 'languageBias' in request)
        self.assertLoggedEqual("part count", 1, len(result.parts))
        self.assertLoggedEqual("speaker stripped", None, result.parts[0].speaker)

    def test_auth_failure_readable_error(self):
        """Rejected credentials surface as readable errors, not decode failures."""
        provider = self._provider()
        client = provider.GetTranscriptionClient(SettingsType())

        with patch('httpx.Client') as mock_client:
            mock_response = mock_client.return_value.__enter__.return_value.post.return_value
            mock_response.is_error = True
            mock_response.status_code = 401
            mock_response.text = '{"error": "unauthorized"}'
            with self.assertRaisesRegex(SubtitleError, "credential was not accepted"):
                client.TranscribeChunk(b"fake-audio", "wav", "en")

    def test_validation_requires_key(self):
        """Missing API keys fail validation with a message."""
        with patch.dict(os.environ, {'MUSE_API_KEY': '', 'MODEL_API_KEY': ''}):
            provider = MuseTranscriptionProvider(SettingsType())

            self.assertLoggedEqual("invalid without key", False, provider.ValidateSettings())

    def test_diarization_flag(self):
        """Only the diarize toggle advertises speaker labels."""
        diarized = self._provider(diarize=True).GetTranscriptionClient(SettingsType())
        plain = self._provider(diarize=False).GetTranscriptionClient(SettingsType())

        self.assertLoggedEqual("diarize model", True, diarized.supports_diarization)
        self.assertLoggedEqual("plain model", False, plain.supports_diarization)

if __name__ == '__main__':
    unittest.main()
