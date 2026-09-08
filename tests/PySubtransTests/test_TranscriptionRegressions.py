"""Regression coverage for transcription recovery, dialogue, and usage."""
from datetime import timedelta
from unittest.mock import patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Options import Options
from PySubtrans.Transcription.AudioExtractor import AudioChunk
from PySubtrans.Transcription.TranscriptionAligner import WordTiming
from PySubtrans.Transcription.TranscriptionCoordinator import TranscriptionCoordinator, TranscriptionStatus
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult, TranscriptionSegment
from tests.PySubtransTests.test_Transcription import FakeTranscriptionClient, FakeTranscriptionProvider, FailingTranscriptionClient, stub_media


class TestTranscriptionRegressions(LoggedTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.provider = FakeTranscriptionProvider()
        with patch('PySubtrans.Transcription.AudioExtractor.CheckFfmpegAvailable'):
            self.coordinator = TranscriptionCoordinator(self.provider)

    def _run_failures(self, fail_on : set[int], count : int):
        client = FailingTranscriptionClient(fail_on=fail_on)
        stub_media(self, self.coordinator, [
            AudioChunk(timedelta(seconds=index * 2), timedelta(seconds=(index + 1) * 2))
            for index in range(count)])
        with patch.object(self.provider, 'GetTranscriptionClient', return_value=client):
            project = self.coordinator.CreateTranscriptionProject('readme.md', Options())
        return project, client

    def test_consecutive_failures_return_a_translation_ready_partial_project(self) -> None:
        """Completed billed chunks remain usable after the failure threshold."""
        project, client = self._run_failures({2, 3, 4}, 5)
        self.assertLoggedEqual('partial source lines', 1, project.subtitles.linecount)
        self.assertLoggedGreater('partial project batched', len(project.subtitles.scenes), 0)
        self.assertLoggedEqual('incomplete result', TranscriptionStatus.INCOMPLETE, self.coordinator.status)
        self.assertLoggedIsNotNone('failure detail retained', self.coordinator.last_error)
        self.assertLoggedEqual('stops at failure threshold', 4, client.calls)

    def test_isolated_failed_chunk_marks_output_incomplete(self) -> None:
        """Continuing after a failed chunk does not report complete subtitles."""
        project, client = self._run_failures({2}, 3)
        self.assertLoggedEqual('successful chunks retained', 2, project.subtitles.linecount)
        self.assertLoggedEqual('all chunks attempted', 3, client.calls)
        self.assertLoggedEqual('missing chunk disclosed', TranscriptionStatus.INCOMPLETE, self.coordinator.status)

    def test_empty_response_still_counts_billed_usage(self) -> None:
        """Music or noise can produce empty text while still incurring charges."""
        client = FakeTranscriptionClient()
        chunk = AudioChunk(timedelta(), timedelta(seconds=2))
        with patch.object(self.coordinator.extractor, 'ReadChunkBytes', return_value=b'audio'), \
                patch.object(self.coordinator.extractor, 'IsSilent', return_value=False), \
                patch.object(client, 'TranscribeChunk', return_value=TranscriptionResult(text='', cost=0.125)):
            result = self.coordinator._transcribe_chunk(client, 'readme.md', chunk)
        self.assertLoggedEqual('no subtitle from empty text', None, result)
        self.assertLoggedEqual('billed usage retained', 0.125, self.coordinator.total_cost)

    def test_dialogue_survives_project_cleanup(self) -> None:
        """Default project processing preserves merged turns and clears attribution."""
        self.provider.words = [
            WordTiming('I say!', timedelta(), timedelta(seconds=0.5), 'A'),
            WordTiming('Of course!', timedelta(seconds=0.6), timedelta(seconds=0.8), 'B'),
            WordTiming('Indeed!', timedelta(seconds=0.9), timedelta(seconds=1.1), 'C')]
        stub_media(self, self.coordinator, [AudioChunk(timedelta(), timedelta(seconds=2))])
        project = self.coordinator.CreateTranscriptionProject('readme.md', Options({
            'postprocess_transcription': True, 'normalise_dialog_tags': True,
            'break_long_lines': False}))
        originals = project.subtitles.originals or []
        self.assertLoggedEqual('one merged subtitle', 1, len(originals))
        self.assertLoggedEqual('dialogue retained', '- I say!\n- Of course!\n- Indeed!', originals[0].text)
        self.assertLoggedEqual('no single speaker attribution', None, originals[0].metadata.get('speaker'))

    def test_leading_sliver_merges_into_existing_dialogue(self) -> None:
        """A mixed right-hand neighbour retains all markers without duplication."""
        lines = self.coordinator._merge_slivers([
            TranscriptionSegment(timedelta(), timedelta(seconds=0.2), 'A', speaker='A'),
            TranscriptionSegment(timedelta(seconds=0.3), timedelta(seconds=1.0), '- B\n- C')])
        self.assertLoggedEqual('merged text', '- A\n- B\n- C', lines[0].text)
        self.assertLoggedEqual('mixed attribution stays empty', None, lines[0].speaker)

    def test_standalone_quote_tokens_and_cjk_punctuation(self) -> None:
        """Split quote tokens must not add spaces inside a quoted phrase."""
        self.assertLoggedEqual('quote tokens', 'He said "Hello world." Then',
                               self.coordinator._join_words(['He', 'said', '"', 'Hello', 'world.', '"', 'Then']))
        self.assertLoggedEqual('CJK punctuation', '你好，世界',
                               self.coordinator._join_words(['你好', '，', '世界']))
