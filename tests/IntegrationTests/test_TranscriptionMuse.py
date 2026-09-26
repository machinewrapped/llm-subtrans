import json
import os
import unittest
from datetime import timedelta
from unittest.mock import Mock, patch

from PySubtrans.Helpers.Speech import EstimateSpeechSeconds
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.SettingsType import SettingsType
from PySubtrans.Transcription.LineSettings import (DEFAULT_MERGE_ELIGIBLE_GAP_SECONDS,
                                                   DEFAULT_SAME_SPEAKER_MERGE_ELIGIBLE_GAP_SECONDS)
from PySubtrans.Transcription.TranscriptionProvider import OptionsScope
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.Providers.Provider_Muse import (
    MuseTranscriptionProvider,
)
from PySubtrans.Transcription.Providers.Clients.MuseTranscriptionClient import (
    TURN_SPEECH_MULTIPLE,
    _parse_muse_payload,
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

    def test_progressive_options_without_key(self):
        """Only the key shows until one is set."""
        with patch.dict(os.environ, {'MUSE_API_KEY': '', 'MODEL_API_KEY': ''}):
            provider = MuseTranscriptionProvider(SettingsType())
            options = provider.GetOptions(provider.settings)

            self.assertLoggedEqual("only api_key", ['api_key'], sorted(options.keys()))

    def test_progressive_options_with_key(self):
        """A non-empty key unlocks the full schema."""
        provider = MuseTranscriptionProvider(SettingsType({'api_key': 'k'}))
        options = provider.GetOptions(provider.settings)

        for key in ('api_key', 'model', 'language', 'diarize', 'request_timeout', 'rate_limit'):
            self.assertLoggedIn(f"{key} option", key, options)

    def test_line_assembly_options_follow_diarization(self):
        """The speaker settings appear only when the provider will label speakers."""
        without = MuseTranscriptionProvider(SettingsType({'api_key': 'k', 'diarize': False}))
        options = without.GetOptions(without.settings)

        self.assertLoggedIn("gap always offered", 'merge_eligible_gap', options)
        self.assertLoggedNotIn("no same-speaker gap", 'same_speaker_merge_eligible_gap', options)
        self.assertLoggedNotIn("no speaker merge toggle", 'can_merge_different_speakers', options)

        with_speakers = MuseTranscriptionProvider(SettingsType({'api_key': 'k', 'diarize': True}))
        options = with_speakers.GetOptions(with_speakers.settings)

        self.assertLoggedIn("same-speaker gap offered", 'same_speaker_merge_eligible_gap', options)
        self.assertLoggedIn("speaker merge toggle offered", 'can_merge_different_speakers', options)

    def test_line_assembly_settings_are_always_present(self):
        """Every provider declares the line assembly settings, at the shared defaults."""
        provider = MuseTranscriptionProvider(SettingsType({'api_key': 'k'}))

        self.assertLoggedEqual("merge gap", DEFAULT_MERGE_ELIGIBLE_GAP_SECONDS,
                               provider.settings.get_float('merge_eligible_gap'))
        self.assertLoggedEqual("same speaker gap", DEFAULT_SAME_SPEAKER_MERGE_ELIGIBLE_GAP_SECONDS,
                               provider.settings.get_float('same_speaker_merge_eligible_gap'))

    def test_saved_line_assembly_settings_win(self):
        """A stored value beats the default."""
        provider = MuseTranscriptionProvider(SettingsType({'api_key': 'k', 'merge_eligible_gap': 0.3}))

        self.assertLoggedEqual("saved gap", 0.3, provider.settings.get_float('merge_eligible_gap'))

    def test_per_run_scope_offers_only_per_job_choices(self):
        """Settings decided once stay out of the schema the Transcribe dialog asks for."""
        provider = MuseTranscriptionProvider(SettingsType({'api_key': 'k'}))
        options = provider.GetOptions(provider.settings, OptionsScope.PER_RUN)

        for key in ('model', 'language', 'diarize'):
            self.assertLoggedIn(f"{key} offered per run", key, options)

        for key in ('request_timeout', 'rate_limit', 'merge_eligible_gap'):
            self.assertLoggedNotIn(f"{key} withheld per run", key, options)

    def test_information_exposed(self):
        """GetInformation() composes the ffmpeg paragraph with provider text."""
        provider = MuseTranscriptionProvider(SettingsType({'api_key': 'k'}))

        info = provider.GetInformation(ffmpeg_available=True)

        self.assertLoggedIsNotNone("info present", info)
        self.assertLoggedNotIn("no ffmpeg paragraph when proven", "ffmpeg", (info or "").casefold())
        self.assertLoggedIn("provider text present", "Muse", info or "")

    def test_information_no_key_walkthrough(self):
        """Missing keys select the setup walkthrough instead of the base text."""
        with patch.dict(os.environ, {'MUSE_API_KEY': '', 'MODEL_API_KEY': ''}):
            provider = MuseTranscriptionProvider(SettingsType())

            info = provider.GetInformation(ffmpeg_available=True)

        self.assertLoggedIsNotNone("walkthrough present", info)
        self.assertLoggedIn("key link", "Model API", info or "")

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
        text, parts = _parse_muse_payload(payload)

        self.assertLoggedEqual("text", "How is the weather? It is raining.", text)
        self.assertLoggedEqual("part count", 2, len(parts))
        self.assertLoggedEqual("first speaker", "A", parts[0].speaker)
        self.assertLoggedEqual("first start", timedelta(seconds=1.52), parts[0].start)
        self.assertLoggedEqual("first end honoured", timedelta(seconds=2.46), parts[0].end)
        expected_end = min(8.0, 5.9 + TURN_SPEECH_MULTIPLE * EstimateSpeechSeconds('It is raining.'))
        self.assertLoggedEqual("last end bounded", timedelta(seconds=expected_end), parts[1].end)

    def test_missing_end_falls_back_to_next_start(self):
        """A turn without endMs runs until the next turn starts, when its text takes that long to say."""

        payload = {
            'transcript': '你一千万赏金都没事 yo',
            'turns': [
                {'speaker': 'A', 'transcript': '你一千万赏金都没事', 'startMs': 0},
                {'speaker': 'B', 'transcript': 'yo', 'startMs': 2000, 'endMs': 3000},
            ],
        }
        _text, parts = _parse_muse_payload(payload)

        self.assertLoggedEqual("part count", 2, len(parts))
        self.assertLoggedEqual("chained end", timedelta(seconds=2.0), parts[0].end)

    def test_missing_end_before_silence_is_capped(self):
        """A turn without endMs does not run on through the silence before the next turn."""

        payload = {
            'transcript': '哎呀，点啊。 好。',
            'turns': [
                {'speaker': 'A', 'transcript': '哎呀，点啊。', 'startMs': 0},
                {'speaker': 'B', 'transcript': '好。', 'startMs': 30000, 'endMs': 30500},
            ],
        }
        _text, parts = _parse_muse_payload(payload)

        expected = TURN_SPEECH_MULTIPLE * EstimateSpeechSeconds('哎呀，点啊。')
        self.assertLoggedEqual("capped end", timedelta(seconds=expected), parts[0].end)

    def test_reported_end_over_silence_is_capped(self):
        """A reported end far beyond what the text takes to say is pulled in, keeping the start."""

        payload = {
            'transcript': '哎呀，点啊，我唔生啊。',
            'turns': [
                {'speaker': 'A', 'transcript': '哎呀，点啊，我唔生啊。', 'startMs': 18780, 'endMs': 47020},
            ],
        }
        _text, parts = _parse_muse_payload(payload)

        expected = 18.78 + TURN_SPEECH_MULTIPLE * EstimateSpeechSeconds('哎呀，点啊，我唔生啊。')
        self.assertLoggedEqual("start kept", timedelta(seconds=18.78), parts[0].start)
        self.assertLoggedEqual("end capped", timedelta(seconds=expected), parts[0].end)

    def test_long_turn_sentences_start_and_end_with_it(self):
        """A long turn's first sentence starts with it and its last ends with it, with silence between."""

        payload = {
            'transcript': '神经。 你生平学过啲咩绝招啊即管使曬出嚟啦。',
            'turns': [
                {'speaker': 'A', 'transcript': '神经。 你生平学过啲咩绝招啊即管使曬出嚟啦。', 'startMs': 3000, 'endMs': 30000},
            ],
        }
        _text, parts = _parse_muse_payload(payload)

        self.assertLoggedEqual("texts", ["神经。", "你生平学过啲咩绝招啊即管使曬出嚟啦。"], [part.text for part in parts])
        self.assertLoggedEqual("first starts with the turn", timedelta(seconds=3.0), parts[0].start)
        self.assertLoggedEqual("first capped", timedelta(seconds=3.0 + TURN_SPEECH_MULTIPLE * EstimateSpeechSeconds("神经。")), parts[0].end)
        self.assertLoggedEqual("last ends with the turn", timedelta(seconds=30.0), parts[1].end)
        self.assertLoggedLess("last starts late in the turn", timedelta(seconds=20.0), parts[1].start)

    def test_full_stops_divide_a_turn(self):
        """Sentences ended by full stops are placed separately, so the last ends with the turn."""

        payload = {
            'transcript': 'Wait. I know where he went.',
            'turns': [
                {'speaker': 'A', 'transcript': 'Wait. I know where he went.', 'startMs': 3000, 'endMs': 30000},
            ],
        }
        _text, parts = _parse_muse_payload(payload)

        self.assertLoggedEqual("texts", ["Wait.", "I know where he went."], [part.text for part in parts])
        self.assertLoggedEqual("last ends with the turn", timedelta(seconds=30.0), parts[1].end)

    def test_short_turn_shares_its_span_between_sentences(self):
        """A turn too short for its sentences divides its span by their characters."""

        payload = {
            'transcript': '表哥。你怕唔惊啊。',
            'turns': [
                {'speaker': 'B', 'transcript': '表哥。你怕唔惊啊。', 'startMs': 0, 'endMs': 1800},
            ],
        }
        _text, parts = _parse_muse_payload(payload)

        self.assertLoggedEqual("part count", 2, len(parts))
        self.assertLoggedEqual("contiguous", parts[0].end, parts[1].start)
        self.assertLoggedEqual("span kept", timedelta(seconds=1.8), parts[1].end)
        self.assertLoggedEqual("speaker kept", "B", parts[1].speaker)

    def test_plausible_reported_end_is_kept(self):
        """A reported end within the speaking time of its text is honoured."""

        payload = {
            'transcript': '你一千万赏金都没事。',
            'turns': [
                {'speaker': 'A', 'transcript': '你一千万赏金都没事。', 'startMs': 1000, 'endMs': 3500},
            ],
        }
        _text, parts = _parse_muse_payload(payload)

        self.assertLoggedEqual("reported end", timedelta(seconds=3.5), parts[0].end)

    def test_zero_length_turn_is_kept(self):
        """A turn reported with no length keeps its text, lasting as long as it takes to say."""

        payload = {
            'transcript': 'Yeah! 我吹先。',
            'turns': [
                {'speaker': 'A', 'transcript': 'Yeah!', 'startMs': 8700, 'endMs': 8700},
                {'speaker': 'B', 'transcript': '我吹先。', 'startMs': 20000, 'endMs': 21000},
            ],
        }
        _text, parts = _parse_muse_payload(payload)

        expected = 8.7 + TURN_SPEECH_MULTIPLE * EstimateSpeechSeconds('Yeah!')
        self.assertLoggedEqual("part count", 2, len(parts))
        self.assertLoggedEqual("given its speaking time", timedelta(seconds=expected), parts[0].end)

    def test_speakers_stripped_unless_opted_in(self):
        """Speaker labels are dropped when diarization is not requested."""

        payload = {
            'transcript': 'hello world',
            'turns': [
                {'speaker': 'A', 'transcript': 'hello world', 'startMs': 0, 'endMs': 1000},
            ],
        }
        text, parts = _parse_muse_payload(payload, include_speakers=False)

        self.assertLoggedEqual("text", "hello world", text)
        self.assertLoggedEqual("part count", 1, len(parts))
        self.assertLoggedEqual("no speaker", None, parts[0].speaker)

    def test_malformed_turns_skipped(self):
        """Empty turns and missing offsets never produce degenerate lines."""

        payload = {
            'transcript': 'ok',
            'turns': ['junk', {'transcript': '', 'startMs': 0.0}, {'transcript': 'ok'}],
        }
        text, parts = _parse_muse_payload(payload, chunk_seconds=5.0)

        self.assertLoggedEqual("text", "ok", text)
        self.assertLoggedEqual("part count", 0, len(parts))

    def test_empty_success_is_returned(self):
        """Music and noise are successful empty responses, not chunk failures."""
        provider = self._provider()
        client = provider.GetTranscriptionClient(SettingsType())

        with patch('httpx.Client') as mock_client:
            post = mock_client.return_value.__enter__.return_value.post
            mock_response = Mock()
            mock_response.is_error = False
            mock_response.status_code = 200
            mock_response.text = '{"transcript": "", "audioDurationMs": 2000, "turns": []}'
            post.return_value = mock_response
            result = client.TranscribeChunk(b"fake-audio", "wav")

        self.assertLoggedEqual("empty text", "", result.text)
        self.assertLoggedEqual("no parts", [], result.parts)
        self.assertLoggedEqual("duration retained", timedelta(seconds=2), result.duration)

    def test_diarize_request_fields(self):
        """Diarize posts DIARIZATION mode with a JSON request part."""
        provider = self._provider(diarize=True)
        client = provider.GetTranscriptionClient(SettingsType({'language': 'en'}))

        with patch('httpx.Client') as mock_client:
            post = mock_client.return_value.__enter__.return_value.post
            mock_response = Mock()
            mock_response.is_error = False
            mock_response.status_code = 200
            mock_response.text = ('{"transcript": "hi", "audioDurationMs": 2000, "turns": ['
                                  '{"speaker": "A", "transcript": "hi", "startMs": 0}]}')
            post.return_value = mock_response
            result = client.TranscribeChunk(b"fake-audio", "wav")

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
        client = provider.GetTranscriptionClient(SettingsType({'language': ''}))

        with patch('httpx.Client') as mock_client:
            post = mock_client.return_value.__enter__.return_value.post
            mock_response = Mock()
            mock_response.is_error = False
            mock_response.status_code = 200
            mock_response.text = ('{"transcript": "hi", "audioDurationMs": 2000, "turns": ['
                                  '{"speaker": "A", "transcript": "hi", "startMs": 0, "endMs": 1000}]}')
            post.return_value = mock_response
            result = client.TranscribeChunk(b"fake-audio", "wav")

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
                client.TranscribeChunk(b"fake-audio", "wav")

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
