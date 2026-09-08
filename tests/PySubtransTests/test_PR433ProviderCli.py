import sys
import unittest
from unittest.mock import Mock, patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
import PySubtrans.Transcription.Providers.Clients.QwenLocalClient as qwen_module
import PySubtrans.Transcription.Providers.Clients.GeminiTranscriptionClient as gemini_module


class TestPR433Qwen(LoggedTestCase):
    def test_auto_detect_requests_timestamps(self):
        """An omitted hint still enables Qwen forced alignment."""
        client_type = getattr(qwen_module, 'QwenLocalClient', None)
        if client_type is None:
            self.skipTest("qwen-asr not installed")
        client = client_type(SettingsType())
        result = type("Result", (), {"text": "hello", "language": "English", "time_stamps": None})()
        model = Mock()
        model.transcribe.return_value = [result]
        client._load_model = Mock(return_value=model)
        client._write_chunk = Mock(return_value="chunk.wav")

        with patch.object(qwen_module.os, 'remove'):
            client._transcribe_chunk(b"audio", "wav", None)

        model.transcribe.assert_called_once_with(
            audio="chunk.wav", language=None, return_time_stamps=True)

    def test_unsupported_detected_language_falls_back_to_text(self):
        """Unsupported forced alignment keeps the detected transcript."""
        client_type = getattr(qwen_module, 'QwenLocalClient', None)
        if client_type is None:
            self.skipTest("qwen-asr not installed")
        client = client_type(SettingsType())
        result = type("Result", (), {"text": "bonjour", "language": "Klingon", "time_stamps": None})()
        model = Mock()
        model.transcribe.side_effect = [ValueError("Unsupported language: Klingon"), [result]]
        client._load_model = Mock(return_value=model)
        client._write_chunk = Mock(return_value="chunk.wav")

        with patch.object(qwen_module.os, 'remove'):
            transcription = client._transcribe_chunk(b"audio", "wav", None)

        self.assertLoggedEqual("fallback text", "bonjour", transcription.text)
        self.assertLoggedEqual("retry count", 2, model.transcribe.call_count)
        self.assertLoggedEqual("fallback timestamps", False,
                               model.transcribe.call_args.kwargs['return_time_stamps'])


class _QuotaError(Exception):
    code = 429


class TestPR433Gemini(LoggedTestCase):
    def _client(self):
        client_type = getattr(gemini_module, 'GeminiTranscriptionClient', None)
        if client_type is None:
            self.skipTest("google-genai not installed")
        return client_type(SettingsType({'api_key': 'key', 'max_retries': 0}))

    def test_upload_deleted_when_generation_fails(self):
        """A failed interaction does not leave uploaded audio behind."""
        client = self._client()
        backend = Mock()
        uploaded = Mock(uri="uri")
        uploaded.name = "uploaded-file"
        backend.files.upload.return_value = uploaded
        backend.interactions.create.side_effect = ValueError("generation failed")

        with self.assertRaises(ValueError):
            client._create_interaction(backend, "chunk.wav", "en")

        backend.files.delete.assert_called_once_with(name="uploaded-file")

    def test_upload_deleted_when_retry_exhausts(self):
        """A quota retry exhaustion cleans up the reused upload."""
        client = self._client()
        backend = Mock()
        uploaded = Mock(uri="uri")
        uploaded.name = "uploaded-file"
        backend.files.upload.return_value = uploaded
        backend.interactions.create.side_effect = _QuotaError("quota exceeded")

        with self.assertRaises(SubtitleError):
            client._create_interaction(backend, "chunk.wav", "en")

        backend.files.delete.assert_called_once_with(name="uploaded-file")


class TestPR433Cli(LoggedTestCase):
    def test_plain_output_passes_postprocess_options(self):
        """Postprocessing applies even when no project file is requested."""
        sys.path.insert(0, 'scripts')
        self.addCleanup(sys.path.remove, 'scripts')
        import transcribe

        subtitles = Mock(linecount=1)
        project = Mock(subtitles=subtitles, projectfile="project.subtrans")
        coordinator = Mock()
        coordinator.CreateTranscriptionProject.return_value = project
        provider = Mock()

        with patch.object(transcribe, 'InitLogger'), \
                patch.object(transcribe.TranscriptionProvider, 'create_provider', return_value=provider), \
                patch.object(transcribe, 'TranscriptionCoordinator', return_value=coordinator), \
                patch.object(transcribe, 'GetOutputPath', return_value='out.vtt'), \
                patch.object(sys, 'argv', ['transcribe.py', 'input.wav', '--no-postprocess']):
            result = transcribe.main()

        self.assertLoggedEqual("exit status", 0, result)
        options = coordinator.CreateTranscriptionProject.call_args.args[1]
        self.assertLoggedEqual("postprocess option", False, options['postprocess_transcription'])
        self.assertLoggedEqual("project persistence", False, options['project_file'])
        subtitles.SaveOriginal.assert_called_once_with('out.vtt')


if __name__ == '__main__':
    unittest.main()
