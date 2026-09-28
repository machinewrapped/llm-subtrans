"""Regression coverage for transcription recovery, dialogue, and usage."""
import logging
from datetime import timedelta
from unittest.mock import patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Options import Options
from PySubtrans.Transcription.AudioChunker import AudioChunk
from PySubtrans.Transcription.WordTiming import WordTiming
from PySubtrans.Transcription.TranscriptionCoordinator import TranscriptionCoordinator, TranscriptionStatus
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult, TranscriptionSegment
from PySubtrans.Transcription.TranscriptionRun import TranscriptionRun
from PySubtrans.SubtitleError import SubtitleError
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
        with self.assertLogs(level=logging.ERROR):
            outcome, client = self._run_failures({2}, 5)
        self.assertLoggedEqual('partial source lines', 1, _subtitles_of(outcome).linecount)
        self.assertLoggedEqual('incomplete result', TranscriptionStatus.INCOMPLETE, outcome.status)
        self.assertLoggedIsNotNone('failure detail retained', outcome.error)
        self.assertLoggedEqual('stops at failure', 2, client.calls)

    def test_empty_response_still_counts_billed_usage(self) -> None:
        """Music or noise can produce empty text while still incurring charges."""
        client = FakeTranscriptionClient()
        chunk = AudioChunk(timedelta(), timedelta(seconds=2))
        run = TranscriptionRun(None)
        with patch.object(self.coordinator.extractor, 'IsSilent', return_value=False), \
                patch.object(client, 'TranscribeChunk', return_value=TranscriptionResult(text='', cost=0.125)):
            result, provider_responded = self.coordinator._transcribe_audio(run, client, chunk, b'audio')
        self.assertLoggedEqual('no subtitle from empty text', None, result)
        self.assertLoggedTrue('provider response recorded', provider_responded)
        self.assertLoggedEqual('billed usage retained', 0.125, run.total_cost)

    def test_empty_provider_chunk_does_not_stop_following_speech(self) -> None:
        """Successful empty chunks do not trigger the coordinator failure policy."""
        client = FakeTranscriptionClient(texts=['', 'speech', ''])
        stub_media(self, self.coordinator, [
            AudioChunk(timedelta(seconds=index * 2), timedelta(seconds=(index + 1) * 2))
            for index in range(3)])

        with patch.object(self.provider, 'GetTranscriptionClient', return_value=client):
            outcome = self.coordinator.CreateTranscription('readme.md', Options())

        self.assertLoggedEqual('speech survives empty chunks', 1, _subtitles_of(outcome).linecount)
        self.assertLoggedEqual('run completed', TranscriptionStatus.COMPLETED, outcome.status)
        self.assertLoggedEqual('all chunks attempted', 3, client.calls)

    def test_dialogue_survives_postprocessing(self) -> None:
        """Post-processing preserves merged turns and clears attribution."""
        self.provider.texts = ['I say! Of course! Indeed!']
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

    def test_extraction_failure_stops_run(self) -> None:
        """An ffmpeg extraction failure stops the run — no unfillable gaps."""
        chunks = [
            AudioChunk(timedelta(seconds=index * 2), timedelta(seconds=(index + 1) * 2))
            for index in range(4)]

        client = FakeTranscriptionClient()
        patch.object(self.coordinator.chunker, "PlanChunksStream",
                     side_effect=lambda *a, **kw: (c for c in chunks)).start()
        patch.object(self.coordinator.extractor, "ReadChunkBytes",
                     side_effect=SubtitleError("ffmpeg read failed")).start()
        self.addCleanup(patch.stopall)

        with patch.object(self.provider, 'GetTranscriptionClient', return_value=client):
            with self.assertLogs(level=logging.ERROR):
                outcome = self.coordinator.CreateTranscription('readme.md', Options())

        # Extraction is local and free — skipping a chunk would leave a
        # gap the user has no way to fill, so the run fails cleanly.
        self.assertLoggedEqual('clean failure', TranscriptionStatus.FAILED, outcome.status)
        self.assertLoggedEqual('nothing charged', 0, client.calls)

    def test_leading_sliver_merges_into_existing_dialogue(self) -> None:
        """A mixed right-hand neighbour retains all markers without duplication."""
        lines = self.coordinator.line_builder.merger.MergeSlivers([
            TranscriptionSegment(timedelta(), timedelta(seconds=0.2), 'A', speaker='A'),
            TranscriptionSegment(timedelta(seconds=0.3), timedelta(seconds=1.0), '- B\n- C')])
        self.assertLoggedEqual('merged text', '- A\n- B\n- C', lines[0].text)
        self.assertLoggedEqual('mixed attribution stays empty', None, lines[0].speaker)
