"""Regression coverage for transcription recovery, dialogue, and usage."""
from datetime import timedelta
from unittest.mock import patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Options import Options
from PySubtrans.Transcription.AudioExtractor import AudioChunk
from PySubtrans.Transcription.TranscriptionAligner import WordTiming
from PySubtrans.Transcription.TranscriptionCoordinator import TranscriptionCoordinator, TranscriptionStatus, _TranscriptionRun
from PySubtrans.Transcription.TranscriptionLines import JoinWords
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult, TranscriptionSegment
from tests.PySubtransTests.test_Transcription import FakeTranscriptionClient, FakeTranscriptionProvider, FailingTranscriptionClient, _subtitles_of, stub_media


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
            outcome = self.coordinator.CreateTranscription('readme.md', Options())
        return outcome, client

    def test_mid_run_failure_returns_partial_result(self) -> None:
        """Completed billed chunks remain usable after a mid-run failure."""
        outcome, client = self._run_failures({2}, 5)
        self.assertLoggedEqual('partial source lines', 1, _subtitles_of(outcome).linecount)
        self.assertLoggedEqual('incomplete result', TranscriptionStatus.INCOMPLETE, outcome.status)
        self.assertLoggedIsNotNone('failure detail retained', outcome.error)
        self.assertLoggedEqual('stops at failure', 2, client.calls)

    def test_empty_response_still_counts_billed_usage(self) -> None:
        """Music or noise can produce empty text while still incurring charges."""
        client = FakeTranscriptionClient()
        chunk = AudioChunk(timedelta(), timedelta(seconds=2))
        run = _TranscriptionRun(None)
        with patch.object(self.coordinator.extractor, 'ReadChunkBytes', return_value=b'audio'), \
                patch.object(self.coordinator.extractor, 'IsSilent', return_value=False), \
                patch.object(client, 'TranscribeChunk', return_value=TranscriptionResult(text='', cost=0.125)):
            result, provider_responded = self.coordinator._transcribe_chunk(run, client, 'readme.md', chunk)
        self.assertLoggedEqual('no subtitle from empty text', None, result)
        self.assertLoggedTrue('provider response recorded', provider_responded)
        self.assertLoggedEqual('billed usage retained', 0.125, run.total_cost)

    def test_dialogue_survives_postprocessing(self) -> None:
        """Post-processing preserves merged turns and clears attribution."""
        self.provider.words = [
            WordTiming('I say!', timedelta(), timedelta(seconds=0.5), 'A'),
            WordTiming('Of course!', timedelta(seconds=0.6), timedelta(seconds=0.8), 'B'),
            WordTiming('Indeed!', timedelta(seconds=0.9), timedelta(seconds=1.1), 'C')]
        stub_media(self, self.coordinator, [AudioChunk(timedelta(), timedelta(seconds=2))])
        outcome = self.coordinator.CreateTranscription('readme.md', Options({
            'postprocess_transcription': True, 'normalise_dialog_tags': True,
            'break_long_lines': False}))
        subtitles = _subtitles_of(outcome)
        originals = subtitles.originals or []
        self.assertLoggedEqual('one merged subtitle', 1, len(originals))
        self.assertLoggedEqual('dialogue retained', '- I say!\n- Of course!\n- Indeed!', originals[0].text)
        self.assertLoggedEqual('no single speaker attribution', None, originals[0].metadata.get('speaker'))

    def test_leading_sliver_merges_into_existing_dialogue(self) -> None:
        """A mixed right-hand neighbour retains all markers without duplication."""
        lines = self.coordinator.line_builder.MergeSlivers([
            TranscriptionSegment(timedelta(), timedelta(seconds=0.2), 'A', speaker='A'),
            TranscriptionSegment(timedelta(seconds=0.3), timedelta(seconds=1.0), '- B\n- C')])
        self.assertLoggedEqual('merged text', '- A\n- B\n- C', lines[0].text)
        self.assertLoggedEqual('mixed attribution stays empty', None, lines[0].speaker)

    def test_standalone_quote_tokens_and_cjk_punctuation(self) -> None:
        """Split quote tokens must not add spaces inside a quoted phrase."""
        self.assertLoggedEqual('quote tokens', 'He said "Hello world." Then',
                               JoinWords(['He', 'said', '"', 'Hello', 'world.', '"', 'Then']))
        self.assertLoggedEqual('CJK punctuation', '你好，世界',
                               JoinWords(['你好', '，', '世界']))
