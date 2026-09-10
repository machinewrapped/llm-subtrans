"""Command-line options for scripts/transcribe.py (no media or backends needed)."""
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'scripts')))

import transcribe  # type: ignore[import-not-found] - scripts dir added to sys.path above

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import skip_if_debugger_attached
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionCoordinator import TranscriptionOutcome, TranscriptionStatus


class TestTranscribeCliOptions(LoggedTestCase):
    def _parse(self, *argv : str):
        return transcribe.CreateTranscribeParser().parse_args(list(argv))

    def test_format_defaults_to_vtt(self):
        """Transcribed output defaults to VTT to preserve speakers."""
        args = self._parse("movie.mkv")

        self.assertLoggedEqual("default format", "vtt", args.format)

    def test_format_srt_selected(self):
        """SRT output is selectable (drops speaker labels)."""
        args = self._parse("movie.mkv", "--format", "srt")

        self.assertLoggedEqual("srt format", "srt", args.format)

    def test_format_ass_selected(self):
        """ASS output is selectable."""
        args = self._parse("movie.mkv", "--format", "ass")

        self.assertLoggedEqual("ass format", "ass", args.format)

    def test_format_vtt_selected(self):
        """VTT output is selectable."""
        args = self._parse("movie.mkv", "--format", "vtt")

        self.assertLoggedEqual("vtt format", "vtt", args.format)

    def test_chunk_bounds_default_to_provider(self):
        """Chunk bounds stay unset so provider recommendations apply."""
        args = self._parse("movie.mkv")

        self.assertLoggedEqual("min unset", None, args.min_chunk)
        self.assertLoggedEqual("max unset", None, args.max_chunk)

    def test_postprocess_defaults_on(self):
        """Transcribed lines are cleaned by default."""
        args = self._parse("movie.mkv")

        self.assertLoggedEqual("postprocess on", True, args.postprocess)

    def test_no_postprocess_disables_cleaning(self):
        """Raw transcription text is available on request."""
        args = self._parse("movie.mkv", "--no-postprocess")

        self.assertLoggedEqual("postprocess off", False, args.postprocess)


class TestTranscribeCliExecution(LoggedTestCase):
    def test_invalid_provider_settings_return_nonzero_before_transcription(self):
        """CLI validation prevents extraction when provider settings are invalid."""
        provider = Mock()
        provider.ValidateSettings.return_value = False
        provider.validation_message = "API Key is required"

        with patch.object(transcribe, 'InitLogger'), \
                patch.object(transcribe.TranscriptionProvider, 'create_provider', return_value=provider), \
                patch.object(transcribe, 'TranscriptionCoordinator') as coordinator_factory, \
                patch.object(sys, 'argv', ['transcribe.py', 'input.wav']):
            result = transcribe.main()

        self.assertLoggedEqual("invalid provider status", 1, result)
        self.assertLoggedEqual("provider validation called", 1, provider.ValidateSettings.call_count)
        self.assertLoggedEqual("transcription not started", 0, coordinator_factory.call_count)

    def test_plain_output_passes_postprocess_options(self):
        """Postprocessing applies even when no project file is requested."""
        subtitles = Mock(linecount=1)
        coordinator = Mock()
        coordinator.CreateTranscription.return_value = TranscriptionOutcome(TranscriptionStatus.COMPLETED, subtitles)
        provider = Mock()

        with patch.object(transcribe, 'InitLogger'), \
                patch.object(transcribe.TranscriptionProvider, 'create_provider', return_value=provider), \
                patch.object(transcribe, 'TranscriptionCoordinator', return_value=coordinator), \
                patch.object(transcribe, 'GetOutputPath', return_value='out.vtt'), \
                patch.object(sys, 'argv', ['transcribe.py', 'input.wav', '--no-postprocess']):
            result = transcribe.main()

        self.assertLoggedEqual("exit status", 0, result)
        options = coordinator.CreateTranscription.call_args.args[1]
        self.assertLoggedEqual("postprocess option", False, options['postprocess_transcription'])
        subtitles.SaveOriginal.assert_called_once_with('out.vtt')

    @skip_if_debugger_attached
    def test_save_failure_returns_nonzero(self):
        """An output write failure is reported as a failed CLI run."""
        subtitles = Mock(linecount=1)
        subtitles.SaveOriginal.side_effect = OSError("permission denied")
        coordinator = Mock()
        coordinator.CreateTranscription.return_value = TranscriptionOutcome(TranscriptionStatus.COMPLETED, subtitles)

        with patch.object(transcribe, 'InitLogger'), \
                patch.object(transcribe.TranscriptionProvider, 'create_provider', return_value=Mock()), \
                patch.object(transcribe, 'TranscriptionCoordinator', return_value=coordinator), \
                patch.object(transcribe, 'GetOutputPath', return_value='out.vtt'), \
                patch.object(sys, 'argv', ['transcribe.py', 'input.wav']):
            result = transcribe.main()

        self.assertLoggedEqual("save failure status", 1, result)

    def test_postprocess_defaults_on_for_plain_output(self):
        """Plain subtitle output retains the default cleaning option."""
        subtitles = Mock(linecount=1)
        coordinator = Mock()
        coordinator.CreateTranscription.return_value = TranscriptionOutcome(TranscriptionStatus.COMPLETED, subtitles)

        with patch.object(transcribe, 'InitLogger'), \
                patch.object(transcribe.TranscriptionProvider, 'create_provider', return_value=Mock()), \
                patch.object(transcribe, 'TranscriptionCoordinator', return_value=coordinator), \
                patch.object(transcribe, 'GetOutputPath', return_value='out.vtt'), \
                patch.object(sys, 'argv', ['transcribe.py', 'input.wav']):
            transcribe.main()

        options = coordinator.CreateTranscription.call_args.args[1]
        self.assertLoggedEqual("default postprocess", True, options['postprocess_transcription'])

    def test_incomplete_run_saves_output_and_returns_nonzero(self):
        """Partial transcription output remains recoverable and is reported incomplete."""
        subtitles = Mock(linecount=1)
        coordinator = Mock()
        coordinator.CreateTranscription.return_value = TranscriptionOutcome(
            TranscriptionStatus.INCOMPLETE, subtitles, error=SubtitleError("chunk failed"))

        with patch.object(transcribe, 'InitLogger'), \
                patch.object(transcribe.TranscriptionProvider, 'create_provider', return_value=Mock()), \
                patch.object(transcribe, 'TranscriptionCoordinator', return_value=coordinator), \
                patch.object(transcribe, 'GetOutputPath', return_value='out.vtt'), \
                patch.object(sys, 'argv', ['transcribe.py', 'input.wav']):
            result = transcribe.main()

        self.assertLoggedEqual("incomplete status", 1, result)
        subtitles.SaveOriginal.assert_called_once_with('out.vtt')


if __name__ == '__main__':
    unittest.main()
