"""Convenience functions for transcription in the PySubtrans package (no media or backends needed)."""
import unittest
from unittest.mock import Mock, patch

import PySubtrans
from PySubtrans import (
    Options,
    TranscriptionCoordinator,
    TranscriptionProvider,
    init_subtitles,
    init_transcription,
    init_transcription_provider,
    transcribe_media,
)
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import log_input_expected_error, skip_if_debugger_attached
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Subtitles import Subtitles
from PySubtrans.Transcription.TranscriptionOutcome import TranscriptionOutcome, TranscriptionStatus


def _mock_provider(valid : bool = True, resolved_language : str|None = None, settings : SettingsType|None = None) -> Mock:
    """A transcription provider that needs no backend."""
    provider = Mock(spec=TranscriptionProvider)
    provider.name = "Mock Transcription"
    provider.settings = settings or SettingsType()
    provider.transcribe_whole_clip = False
    provider.validation_message = None if valid else "API key is required"
    provider.ValidateSettings.return_value = valid
    provider.ResolveLanguageCode.return_value = resolved_language
    return provider


class InitTranscriptionTests(LoggedTestCase):
    def _init(self, provider : Mock, **settings) -> SettingsType:
        """Run init_transcription by provider name and return the settings the coordinator received."""
        with patch.object(TranscriptionProvider, 'create_provider', return_value=provider), \
                patch.object(PySubtrans, 'TranscriptionCoordinator') as coordinator_factory:
            init_transcription("Mock Transcription", **settings)

        self.assertLoggedEqual("coordinator created", 1, coordinator_factory.call_count)
        return coordinator_factory.call_args.args[1]

    def test_resolved_language_passes_to_coordinator(self) -> None:
        """The coordinator receives the provider's resolved language code, not the raw hint."""
        settings = self._init(_mock_provider(resolved_language="cmn-Hans-CN"), language="Chinese")

        self.assertLoggedEqual("coordinator language", "cmn-Hans-CN", settings.get_str('language'))

    def test_line_limits_default_to_options(self) -> None:
        """Line limits that are not supplied are taken from the Options defaults."""
        settings = self._init(_mock_provider(), max_characters=80)

        self.assertLoggedEqual("explicit max_characters", 80, settings.get_int('max_characters'))
        self.assertLoggedEqual("default max_line_duration", Options().get_float('max_line_duration'), settings.get_float('max_line_duration'))
        self.assertLoggedEqual("default abbreviations", Options().get_list('abbreviations'), settings.get_list('abbreviations'))

    def test_translation_defaults_do_not_reach_coordinator(self) -> None:
        """Translation defaults in Options must not override the provider's own client settings."""
        settings = self._init(_mock_provider())

        self.assertLoggedNotIn("max_retries absent", 'max_retries', settings)
        self.assertLoggedNotIn("target_language absent", 'target_language', settings)

    def test_explicit_settings_pass_to_provider_and_coordinator(self) -> None:
        """Settings reach both the provider and the coordinator, and unset values are dropped."""
        provider = _mock_provider()

        with patch.object(TranscriptionProvider, 'create_provider', return_value=provider) as create_provider, \
                patch.object(PySubtrans, 'TranscriptionCoordinator') as coordinator_factory:
            init_transcription("Mock Transcription", api_key="key", model=None, ffmpeg_path="/tools/ffmpeg", diarize=None)

        provider_settings = create_provider.call_args.args[1]
        coordinator_settings = coordinator_factory.call_args.args[1]
        self.assertLoggedEqual("provider api_key", "key", provider_settings.get_str('api_key'))
        self.assertLoggedNotIn("unset model dropped", 'model', provider_settings)
        self.assertLoggedNotIn("unset diarize dropped", 'diarize', provider_settings)
        self.assertLoggedEqual("coordinator ffmpeg_path", "/tools/ffmpeg", coordinator_settings.get_str('ffmpeg_path'))

    def test_provider_instance_is_used(self) -> None:
        """A provider created with init_transcription_provider can be passed in place of a name."""
        provider = _mock_provider(settings=SettingsType({'language': 'Japanese'}), resolved_language="ja")

        with patch.object(TranscriptionProvider, 'create_provider') as create_provider, \
                patch.object(PySubtrans, 'TranscriptionCoordinator') as coordinator_factory:
            init_transcription(provider)

        self.assertLoggedEqual("no provider created", 0, create_provider.call_count)
        self.assertLoggedIs("coordinator provider", provider, coordinator_factory.call_args.args[0])
        self.assertLoggedEqual("language from provider settings", "ja", coordinator_factory.call_args.args[1].get_str('language'))

    def test_returns_coordinator(self) -> None:
        """init_transcription returns a real coordinator for a valid provider."""
        provider = _mock_provider()
        provider.word_coverage = Mock()

        with patch.object(TranscriptionProvider, 'create_provider', return_value=provider):
            transcriber = init_transcription("Mock Transcription")

        self.assertLoggedIsInstance("transcriber type", transcriber, TranscriptionCoordinator)

    @skip_if_debugger_attached
    def test_unknown_provider_raises(self) -> None:
        """An unknown provider name is reported as a SubtitleError."""
        with self.assertRaises(SubtitleError) as exc:
            init_transcription("No Such Provider")

        log_input_expected_error("No Such Provider", SubtitleError, exc.exception)

    @skip_if_debugger_attached
    def test_invalid_provider_settings_raise(self) -> None:
        """Invalid provider settings stop initialisation before a coordinator is created."""
        with patch.object(TranscriptionProvider, 'create_provider', return_value=_mock_provider(valid=False)), \
                patch.object(PySubtrans, 'TranscriptionCoordinator') as coordinator_factory:
            with self.assertRaises(SubtitleError) as exc:
                init_transcription("Mock Transcription")

        log_input_expected_error("invalid settings", SubtitleError, exc.exception)
        self.assertLoggedEqual("coordinator not created", 0, coordinator_factory.call_count)

    @skip_if_debugger_attached
    def test_invalid_provider_instance_raises(self) -> None:
        """A provider instance is validated too."""
        with self.assertRaises(SubtitleError) as exc:
            init_transcription(_mock_provider(valid=False))

        log_input_expected_error("invalid provider instance", SubtitleError, exc.exception)

    @skip_if_debugger_attached
    def test_unresolvable_language_raises(self) -> None:
        """A language the provider cannot use stops initialisation."""
        provider = _mock_provider()
        provider.ResolveLanguageCode.side_effect = SubtitleError("Unrecognised language 'Klingon'")

        with patch.object(TranscriptionProvider, 'create_provider', return_value=provider), \
                patch.object(PySubtrans, 'TranscriptionCoordinator') as coordinator_factory:
            with self.assertRaises(SubtitleError) as exc:
                init_transcription("Mock Transcription", language="Klingon")

        log_input_expected_error("Klingon", SubtitleError, exc.exception)
        self.assertLoggedEqual("coordinator not created", 0, coordinator_factory.call_count)

    @skip_if_debugger_attached
    def test_inverted_chunk_bounds_raise(self) -> None:
        """A minimum chunk length above the maximum is rejected."""
        with patch.object(TranscriptionProvider, 'create_provider', return_value=_mock_provider()):
            with self.assertRaises(SubtitleError) as exc:
                init_transcription("Mock Transcription", min_chunk_seconds=60.0, max_chunk_seconds=30.0)

        log_input_expected_error("min 60 > max 30", SubtitleError, exc.exception)

    @skip_if_debugger_attached
    def test_init_transcription_provider_requires_name(self) -> None:
        """A provider name is required."""
        with self.assertRaises(SubtitleError) as exc:
            init_transcription_provider("")

        log_input_expected_error("empty name", SubtitleError, exc.exception)


class TranscribeMediaTests(LoggedTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.srt_content = """1\n00:00:01,000 --> 00:00:04,000\nHello world\n\n2\n00:00:06,000 --> 00:00:09,000\nHow are you?\n"""

    def _transcriber(self, outcome : TranscriptionOutcome) -> Mock:
        """A transcriber that returns *outcome* without touching media."""
        transcriber = Mock(spec=TranscriptionCoordinator)
        transcriber.settings = SettingsType({'scene_threshold': 30.0})
        transcriber.CreateTranscription.return_value = outcome
        return transcriber

    def _subtitles(self) -> Subtitles:
        return init_subtitles(content=self.srt_content, auto_batch=False)

    def test_completed_transcription_is_batched(self) -> None:
        """A completed transcription is returned batched and without an error."""
        subtitles = self._subtitles()
        transcriber = self._transcriber(TranscriptionOutcome(TranscriptionStatus.COMPLETED, subtitles))

        result, error = transcribe_media(transcriber, "movie.mkv")

        self.assertLoggedIs("same subtitles", subtitles, result)
        self.assertLoggedIsNone("no error", error)
        self.assertLoggedGreater("scenes created", result.scenecount, 0)

    def test_transcriber_settings_are_used_by_default(self) -> None:
        """Post-processing settings default to the transcriber's settings."""
        transcriber = self._transcriber(TranscriptionOutcome(TranscriptionStatus.COMPLETED, self._subtitles()))

        transcribe_media(transcriber, "movie.mkv")

        options = transcriber.CreateTranscription.call_args.args[1]
        self.assertLoggedIsInstance("options type", options, Options)
        self.assertLoggedEqual("scene threshold from transcriber", 30.0, options.get_float('scene_threshold'))

    def test_auto_batch_disabled(self) -> None:
        """Batching can be skipped when the transcription is not being translated."""
        transcriber = self._transcriber(TranscriptionOutcome(TranscriptionStatus.COMPLETED, self._subtitles()))

        result, _error = transcribe_media(transcriber, "movie.mkv", auto_batch=False)

        self.assertLoggedEqual("no scenes", 0, result.scenecount)

    def test_incomplete_transcription_returns_error(self) -> None:
        """Lines transcribed before a failure are returned with the error that stopped the run."""
        chunk_error = SubtitleError("chunk failed")
        transcriber = self._transcriber(TranscriptionOutcome(TranscriptionStatus.INCOMPLETE, self._subtitles(), error=chunk_error))

        result, error = transcribe_media(transcriber, "movie.mkv")

        self.assertLoggedIs("error returned", chunk_error, error)
        self.assertLoggedEqual("partial lines kept", 2, result.linecount)

    @skip_if_debugger_attached
    def test_failed_transcription_raises(self) -> None:
        """A transcription that produced nothing raises its error."""
        failure = SubtitleError("No speech found")
        transcriber = self._transcriber(TranscriptionOutcome(TranscriptionStatus.FAILED, error=failure))

        with self.assertRaises(SubtitleError) as exc:
            transcribe_media(transcriber, "movie.mkv")

        log_input_expected_error("failed outcome", SubtitleError, exc.exception)
        self.assertLoggedIs("original error raised", failure, exc.exception)


if __name__ == '__main__':
    unittest.main()
