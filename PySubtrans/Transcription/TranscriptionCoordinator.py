from __future__ import annotations

import logging
import os
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Time import SpanLabel
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.SubtitleProcessor import SubtitleProcessor
from PySubtrans.Subtitles import Subtitles
from PySubtrans.Transcription.AudioChunker import AudioChunker, AudioChunk
from PySubtrans.Transcription.AudioExtractor import AudioExtractor, AudioTrack, CheckFfmpegAvailable
from PySubtrans.Transcription.LineSettings import (DEFAULT_MERGE_ELIGIBLE_GAP_SECONDS, DEFAULT_MIN_GAP_SECONDS,
                                                   DEFAULT_SAME_SPEAKER_MERGE_ELIGIBLE_GAP_SECONDS, LineSettings)
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionCapture import CapturePath, TranscriptionCapture
from PySubtrans.Transcription.TranscriptionEvents import TranscriptionEvents
from PySubtrans.Transcription.TranscriptionLines import TranscriptionLineBuilder
from PySubtrans.Transcription.TranscriptionOutcome import TranscriptionOutcome, TranscriptionStatus
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.TranscriptionRun import TranscriptionRun
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionSegment

class TranscriptionCoordinator:
    """
    End-to-end media to subtitles transcription.

    Extracts coherent audio chunks from a media file, transcribes each chunk with the provider client, and assembles timestamped subtitles.
    Subscribe to `events` for progress and per-line notifications; each run returns a TranscriptionOutcome describing what was produced.
    """
    def __init__(self, provider : TranscriptionProvider, settings : SettingsType|Options|None = None):
        self.provider : TranscriptionProvider = provider
        self.settings : SettingsType = SettingsType(settings or {})
        self.aborted : bool = False

        chunk_settings = SettingsType({
            'min_chunk_seconds': self.settings.get_float('min_chunk_seconds')
                or provider.recommended_min_chunk_seconds,
            'max_chunk_seconds': self.settings.get_float('max_chunk_seconds')
                or provider.recommended_max_chunk_seconds,
            'silence_min_duration': self.settings.get_float('silence_min_duration', 1.0),
            'ffmpeg_path': self.settings.get_str('ffmpeg_path'),
        })
        self.chunker : AudioChunker = AudioChunker(chunk_settings)
        self.extractor : AudioExtractor = self.chunker.extractor

        # Reading the engine's output is provider-specific; the limits a
        # finished line is held to are not
        line_settings = provider.settings

        # Transcribed lines obey the same limits as loaded and translated subtitles
        min_gap = self.settings.get_float('min_gap')
        self.line_builder : TranscriptionLineBuilder = TranscriptionLineBuilder(LineSettings(
            max_line_chars=self.settings.get_int('max_characters') or 120,
            max_line_seconds=self.settings.get_float('max_line_duration') or 4.0,
            min_split_chars=self.settings.get_int('min_split_chars') or 3,
            min_line_seconds=self.settings.get_float('min_line_duration') or 0.8,
            merge_eligible_gap=line_settings.get_float('merge_eligible_gap') or DEFAULT_MERGE_ELIGIBLE_GAP_SECONDS,
            same_speaker_merge_eligible_gap=line_settings.get_float('same_speaker_merge_eligible_gap')
                or DEFAULT_SAME_SPEAKER_MERGE_ELIGIBLE_GAP_SECONDS,
            max_newlines=self.settings.get_int('max_newlines') or 2,
            can_merge_different_speakers=line_settings.get_bool('can_merge_different_speakers', True),
            min_gap=min_gap if min_gap is not None else DEFAULT_MIN_GAP_SECONDS,
            word_coverage=provider.word_coverage))

        self.events : TranscriptionEvents = TranscriptionEvents()
        self._active_client : TranscriptionClient|None = None

        # Raw provider segments, captured on request for offline replay
        self._capture : TranscriptionCapture|None = None

    @property
    def track_index(self) -> int:
        """Audio track to transcribe (0-based within audio streams)."""
        return self.settings.get_int('audio_track') or 0

    @property
    def language(self) -> str|None:
        """Spoken language hint for the transcription engine."""
        return self.settings.get_str('language') or self.provider.settings.get_str('language')

    @property
    def silence_skip_db(self) -> float:
        """Peak level below which chunks skip transcription entirely."""
        return self.settings.get_float('silence_skip_db') or -40.0

    def CheckRequirements(self, media_path : str) -> list[AudioTrack]:
        """
        Verify ffmpeg availability and return the media audio tracks.
        """
        CheckFfmpegAvailable(self.settings)
        return self.extractor.ListAudioTracks(media_path)

    def PlanChunks(self, media_path : str) -> list[AudioChunk]:
        """
        Return the transcription chunk plan without extracting audio.
        """
        return self.chunker.PlanChunks(media_path, self.track_index)

    def TranscribeMedia(self, media_path : str, prior_subtitles : Subtitles|None = None) -> TranscriptionOutcome:
        """
        Transcribe a media file into timestamped subtitles.

        When *prior_subtitles* is supplied (from an earlier aborted run), already-transcribed chunks are skipped and the new lines are appended after the existing ones. 
        Expected failures (missing media, an engine without timings, a blocked run, no speech) are reported as a FAILED outcome rather than raised.
        """
        if not media_path or not os.path.isfile(media_path):
            return self._failed(SubtitleError(_("Media file not found: {}").format(media_path)))

        self.events.status.send(self, text=_("Preparing {} transcription...").format(self.provider.name))

        try:
            client = self._start_client()

        except SubtitleError as e:
            return self._failed(e)

        run = TranscriptionRun(prior_subtitles)

        # Capture raw provider segments when requested (scripts/replay_transcription.py)
        capture_path = CapturePath(self.settings)
        self._capture = TranscriptionCapture(capture_path, self.provider.name, media_path) if capture_path else None

        def on_duration(duration : timedelta) -> None:
            run.audio_total_seconds = max(0.0, duration.total_seconds())
            if run.audio_total_seconds > 0.0:
                self.events.audio_progress.send(self, processed=0.0, total=run.audio_total_seconds)

        chunks = self.chunker.PlanChunksStream(media_path, self.track_index, duration_cb=on_duration)
        logging.info(_("Transcribing {} with {}").format(
            os.path.basename(media_path), self.provider.name))

        try:
            self._run_chunks(run, client, media_path, chunks)

        except SubtitleError as e:
            # A blocked run with nothing transcribed is a failure; a
            # silence-scan failure mid-run must not discard already
            # transcribed (billed) chunks.
            if run.transcribed == 0:
                return self._failed(e)

            run.had_failures = True
            run.error = e
            logging.error(str(e))

        finally:
            chunks.close()
            self._active_client = None

        return self._finish_run(run, media_path)

    def CreateTranscription(self, media_path : str, options : Options|None = None,
                            prior_subtitles : Subtitles|None = None) -> TranscriptionOutcome:
        """Transcribe media and return the outcome with post-processed subtitles."""
        outcome = self.TranscribeMedia(media_path, prior_subtitles=prior_subtitles)

        if outcome.subtitles is not None and options is not None and options.get_bool('postprocess_transcription', True):
            self._process_transcription(outcome.subtitles, options)

        return outcome

    def Abort(self) -> None:
        """Stop transcription after the current chunk."""
        self.aborted = True

        if self._active_client is not None:
            self._active_client.AbortTranscription()

    def _failed(self, error : SubtitleError) -> TranscriptionOutcome:
        """Log and package a run that produced nothing usable."""
        logging.error(str(error), exc_info=error.error or error)
        return TranscriptionOutcome(status=TranscriptionStatus.FAILED, error=error)

    def _start_client(self) -> TranscriptionClient:
        """
        Obtain the provider client, refusing engines that cannot time their output.
        """
        logging.info(_("Creating {} transcription client...").format(self.provider.name))
        client = self.provider.GetTranscriptionClient(self.settings)
        self._active_client = client

        if not client.supports_timestamps:
            self._active_client = None
            raise SubtitleError(_(
                "'{}' cannot provide subtitle timings (no word or segment "
                "timestamps). Transcription without timings has no value "
                "here, so nothing was requested and no credits were spent."
            ).format(self.provider.name))

        return client

    def _run_chunks(self, run : TranscriptionRun, client : TranscriptionClient, media_path : str,
                    chunks : Generator[AudioChunk, None, None]) -> None:
        """
        Transcribe each planned chunk in turn, honouring abort, resume and the failure policy. Partial results stay in run.lines.

        Audio extraction for the next chunk is submitted to a background thread while the current chunk is being transcribed, 
        so ffmpeg I/O overlaps with GPU (or network) inference.
        """
        def report_progress(done : int, chunk : AudioChunk) -> None:
            # Total is unknown while the plan streams in (0 signals that)
            self.events.progress.send(self, done=done, total=0, span=SpanLabel(chunk.start, chunk.end))

        def report_audio(chunk : AudioChunk) -> None:
            if run.audio_total_seconds > 0.0:
                self.events.audio_progress.send(self, processed=run.AudioPosition(chunk), total=run.audio_total_seconds)

        # Manual pool management so we can shutdown(wait=False) on abort
        # instead of blocking until a running ffmpeg extraction finishes.
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='audio-prefetch')

        try:
            # One-chunk lookahead: as each chunk arrives from the generator, we submit its extraction to a background thread.
            # While that runs we transcribe the previous chunk, whose audio is (probably)already available.
            prev_chunk : AudioChunk|None = None
            prev_audio : bytes|None = None
            prev_done : int = -1
            done = 0

            while True:
                # Advance the chunk plan, catching generator errors so the buffered previous chunk can still be processed.
                chunk : AudioChunk|None = None
                plan_error : SubtitleError|None = None

                if done == 0:
                    self.events.status.send(self, text=_("Detecting audio..."))

                try:
                    chunk = next(chunks)
                except StopIteration:
                    pass
                except SubtitleError as e:
                    plan_error = e

                if chunk is not None:
                    # Submit extraction for this chunk right away
                    future = pool.submit(self._extract_audio, media_path, chunk)
                else:
                    future = None

                # Process the previous chunk while extraction runs
                if prev_chunk is not None and prev_audio is not None:
                    stop = self._process_chunk(
                        run, client, prev_chunk, prev_audio, prev_done,
                        report_progress, report_audio)
                    if stop:
                        if future is not None:
                            future.cancel()
                        break

                # Re-raise plan errors after the buffered chunk is processed
                if plan_error is not None:
                    raise plan_error

                # No more chunks
                if chunk is None:
                    break

                # Abort / skip checks for the current chunk
                assert future is not None
                if self.aborted or client.aborted:
                    logging.warning(_("Transcription cancelled after {done} chunks").format(done=done))
                    run.had_failures = True
                    future.cancel()
                    break

                if run.AlreadyDone(chunk):
                    assert future is not None
                    future.cancel()
                    run.chunks_done += 1
                    report_progress(done, chunk)
                    report_audio(chunk)
                    prev_chunk = None
                    prev_audio = None
                    done += 1
                    continue

                # Collect the extracted audio (blocks until ffmpeg finishes).
                # Extraction errors propagate: ffmpeg is local and free, so
                # there is no reason to skip a chunk and leave an unfillable
                # gap. TranscribeMedia preserves any already-transcribed
                # lines when the error surfaces there.
                assert future is not None
                prev_chunk = chunk
                prev_audio = future.result()
                prev_done = done
                done += 1

        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _process_chunk(self, run : TranscriptionRun, client : TranscriptionClient,
                       chunk : AudioChunk, audio_bytes : bytes, done : int,
                       report_progress : Callable[[int, AudioChunk], None],
                       report_audio : Callable[[AudioChunk], None]) -> bool:
        """Transcribe one chunk with pre-extracted audio. Returns True to stop the run."""
        report_progress(done, chunk)

        try:
            segment, provider_responded = self._transcribe_audio(run, client, chunk, audio_bytes)

        except SubtitleError as e:
            report_audio(chunk)
            return self._handle_chunk_failure(run, chunk, e)

        else:
            self._accept_chunk(run, segment, provider_responded)

        report_audio(chunk)
        return False

    def _handle_chunk_failure(self, run : TranscriptionRun, chunk : AudioChunk, error : SubtitleError) -> bool:
        """
        Record a chunk failure and stop the run.

        Skipping a failed chunk is never correct: resume appends after the last line, so a gap can never be filled — the user would be left
        paying for a transcription they cannot complete.  When lines already exist the run stops as INCOMPLETE so the user can resume from where
        it left off; when nothing has been transcribed the error propagates and the run is FAILED.
        """
        run.had_failures = True

        if run.transcribed > 0:
            run.error = SubtitleError(
                _("Transcription stopped at {span}: {error}").format(span=SpanLabel(chunk.start, chunk.end), error=error),
                error=error)
            logging.error(str(run.error))
            return True

        raise SubtitleError(
            _("Transcription failed at {span}: {error}").format(span=SpanLabel(chunk.start, chunk.end), error=error),
            error=error)

    def _accept_chunk(self, run : TranscriptionRun, segment : TranscriptionSegment|None,
                      provider_responded : bool) -> None:
        """Fold a successfully processed chunk into the run."""
        run.chunks_done += 1

        if segment is None:
            return

        # Record the segment as the provider returned it, before line assembly
        if self._capture is not None:
            self._capture.Add(segment)

        for line in self.line_builder.LinesForSegment(segment):
            if run.AddLine(line) is not None:
                self.events.segment.send(self, segment=line)

    def _finish_run(self, run : TranscriptionRun, media_path : str) -> TranscriptionOutcome:
        """Assemble the run's lines into Subtitles and report the outcome."""
        if run.transcribed == 0:
            return self._failed(SubtitleError(_("No timed subtitles could be produced from {}").format(media_path)))

        logging.info(_("Transcribed {} lines from {} chunks").format(run.transcribed, run.chunks_done))

        if run.total_cost > 0:
            logging.info(_("Transcription cost: ${:.4f}").format(run.total_cost))

        subtitles = Subtitles()
        subtitles.originals = run.lines
        subtitles.sourcepath = os.path.normpath(media_path)
        subtitles.file_format = '.srt'

        status = TranscriptionStatus.INCOMPLETE if run.had_failures else TranscriptionStatus.COMPLETED
        return TranscriptionOutcome(status=status, subtitles=subtitles, error=run.error,
                                    transcribed_lines=run.transcribed, total_cost=run.total_cost)

    def _process_transcription(self, subtitles : Subtitles, options : Options) -> None:
        """
        Pre- and post-process transcribed lines (dash normalization, filler
        word removal, dialog breaks, duration-based line splitting).  Works
        on the flat originals list, no batching or scenes involved.
        """
        if not subtitles.originals:
            return

        processor = SubtitleProcessor(SettingsType(options))
        lines = processor.PreprocessSubtitles(subtitles.originals)
        lines = [line for line in processor.PostprocessSubtitles(lines)
                 if line.text and line.text.strip()]

        subtitles.originals = lines

    def _extract_audio(self, media_path : str, chunk : AudioChunk) -> bytes:
        """Extract a chunk's audio via ffmpeg. Safe to call from a background thread."""
        return self.extractor.ReadChunkBytes(media_path, chunk.start, chunk.end, self.track_index)

    def _transcribe_audio(self, run : TranscriptionRun, client : TranscriptionClient,
                          chunk : AudioChunk, audio_bytes : bytes) -> tuple[TranscriptionSegment|None, bool]:
        """
        Transcribe pre-extracted audio. Returns the segment (None for silent
        or empty chunks) and whether the provider was actually asked.
        """
        if self.extractor.IsSilent(audio_bytes, self.silence_skip_db):
            logging.debug(_("Skipping silent chunk {} before requesting").format(SpanLabel(chunk.start, chunk.end)))
            return None, False

        result = client.TranscribeChunk(audio_bytes, 'wav')

        if result.cost:
            run.total_cost += result.cost

        text = (result.text or '').strip()
        if not text:
            logging.debug(_("Empty transcription for chunk {}").format(SpanLabel(chunk.start, chunk.end)))
            return None, True

        return TranscriptionSegment(start=chunk.start, end=chunk.end, text=text,
                                    language=result.language or self.language,
                                    words=result.words, parts=result.parts), True
