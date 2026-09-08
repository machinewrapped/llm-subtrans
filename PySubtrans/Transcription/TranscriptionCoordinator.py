from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import timedelta
from enum import Enum
import unicodedata

import regex

from PySubtrans import batch_subtitles
from PySubtrans.Helpers import GetOutputPath
from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleBuilder import SubtitleBuilder
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.SubtitleProcessor import SubtitleProcessor
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.SubtitleScene import UnbatchScenes
from PySubtrans.Subtitles import Subtitles
from PySubtrans.SubtitleValidator import SubtitleValidator
from PySubtrans.Transcription.AudioExtractor import AudioExtractor, AudioChunk, AudioChunker, CheckFfmpegAvailable
from PySubtrans.Transcription.TranscriptionAligner import WordTiming
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionSegment

# Sentence-ending punctuation across CJK and latin scripts
_SENTENCE_END_CHARS = frozenset('。！？!?\n…')

class TranscriptionStatus(str, Enum):
    """State of the most recent transcription run."""
    IDLE = "idle"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


def _needs_space(previous : str, current : str) -> bool:
    """
    Whether a space belongs between two adjacent aligned units.
    """
    if not previous or not current:
        return False
    previous_category = unicodedata.category(previous)
    current_category = unicodedata.category(current)
    if current_category.startswith('P'):
        return False
    if previous_category.startswith('P'):
        return previous not in '([{"\u2018\u201c'
    previous_word = previous_category[0] in ('L', 'N')
    current_word = current_category[0] in ('L', 'N')
    if not (previous_word and current_word):
        return False
    # CJK scripts conventionally omit spaces between adjacent characters.
    previous_cjk = regex.match(r'\p{Script=Han}|\p{Script=Hiragana}|\p{Script=Katakana}', previous)
    current_cjk = regex.match(r'\p{Script=Han}|\p{Script=Hiragana}|\p{Script=Katakana}', current)
    return not (previous_cjk and current_cjk)

# Lines shorter than this merge into their neighbour (bounds stay truthful)
_MIN_LINE_SECONDS = 0.4

# Signature for transcription progress callbacks: (chunks_completed, chunk_total, current_chunk_span)
TranscriptionProgressCallback = Callable[[int, int, str], None]

# Signature for per-chunk callbacks: invoked with each transcribed segment
TranscriptionSegmentCallback = Callable[[TranscriptionSegment], None]


class TranscriptionCoordinator:
    """
    End-to-end media to subtitles transcription.

    Extracts coherent audio chunks from a media file, transcribes each
    chunk with the provider client, and assembles timestamped subtitles.
    Has no GUI dependencies so CLI and library callers can use it directly.
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
        })
        self.chunker : AudioChunker = AudioChunker(chunk_settings)
        self.extractor : AudioExtractor = self.chunker.extractor
        self._active_client : TranscriptionClient|None = None
        self.total_cost : float = 0.0
        self.status : TranscriptionStatus = TranscriptionStatus.IDLE
        self.last_error : SubtitleError|None = None
        self.partial_subtitles : Subtitles|None = None

    @property
    def track_index(self) -> int:
        """Audio track to transcribe (0-based within audio streams)."""
        return self.settings.get_int('audio_track') or 0

    @property
    def language(self) -> str|None:
        """Spoken language hint for the transcription engine."""
        return self.settings.get_str('language') or self.provider.settings.get_str('language')

    @property
    def max_line_chars(self) -> int:
        """Maximum characters per subtitle line when grouping aligned words."""
        return self.settings.get_int('transcription_max_chars') or 84

    @property
    def max_line_seconds(self) -> float:
        """Maximum duration per subtitle line when grouping aligned words."""
        return self.settings.get_float('transcription_max_line_seconds') or 8.0

    @property
    def word_gap_split(self) -> float:
        """Inter-word pause that forces a new subtitle line, in seconds."""
        return self.settings.get_float('transcription_gap_split') or 0.5

    @property
    def silence_skip_db(self) -> float:
        """Peak level below which chunks skip transcription entirely."""
        return self.settings.get_float('silence_skip_db') or -40.0

    @classmethod
    def ResolveProviderSettings(cls, provider_name : str, settings : SettingsType|Options, options : Options|None = None) -> SettingsType:
        """
        Merge settings with shared credentials from Options.provider_settings.

        Only credentials travel across capabilities (api_key, proxy): endpoint
        conventions differ per capability (translation and transcription use
        different base paths), so server addresses and models are never
        shared. Transcription settings live under "<name> Transcription".
        """
        resolved = SettingsType(settings or {})
        if options is not None and isinstance(options, Options):
            # Membership checks first: provider_settings raises KeyError for
            # unknown providers and missing keys are the expected case here.
            own_key = f"{provider_name} Transcription"
            if own_key in options.provider_settings:
                for k, v in options.provider_settings[own_key].items():
                    if k not in resolved:
                        resolved[k] = v
            if provider_name in options.provider_settings:
                shared = options.provider_settings[provider_name]
                for key in ('api_key', 'proxy'):
                    if not resolved.get(key) and shared.get(key):
                        resolved[key] = shared.get(key)

        return resolved

    @staticmethod
    def SettingsKey(provider_name : str) -> str:
        """
        Settings namespace for a transcription provider, kept separate
        from its translation counterpart (see ResolveProviderSettings).
        """
        return f"{provider_name} Transcription"

    def CheckRequirements(self, media_path : str) -> list[AudioTrackInfo]:
        """
        Verify ffmpeg availability and return the media audio tracks.
        """
        CheckFfmpegAvailable()
        tracks = self.extractor.ListAudioTracks(media_path)
        return [AudioTrackInfo(index=t.index, codec=t.codec, language=t.language) for t in tracks]

    def PlanChunks(self, media_path : str) -> list[AudioChunk]:
        """
        Return the transcription chunk plan without extracting audio.
        """
        return self.chunker.PlanChunks(media_path, self.track_index)

    def TranscribeMedia(self, media_path : str, progress_cb : TranscriptionProgressCallback|None = None,
                        segment_cb : TranscriptionSegmentCallback|None = None) -> Subtitles:
        """
        Transcribe a media file into timestamped subtitles.
        """
        self.status = TranscriptionStatus.IDLE
        self.last_error = None
        self.partial_subtitles = None
        if not media_path or not os.path.isfile(media_path):
            self.status = TranscriptionStatus.FAILED
            raise SubtitleError(_("Media file not found: {}").format(media_path))

        client : TranscriptionClient = self.provider.GetTranscriptionClient(self.settings)
        self._active_client = client
        if not client.supports_timestamps:
            self.status = TranscriptionStatus.FAILED
            raise SubtitleError(_(
                "'{}' cannot provide subtitle timings (no word or segment "
                "timestamps). Transcription without timings has no value "
                "here, so nothing was requested and no credits were spent."
            ).format(self.provider.name))
        chunks = self.chunker.PlanChunks(media_path, self.track_index)
        total = len(chunks)
        logging.info(_("Transcribing {} in {} chunks with {}").format(
            os.path.basename(media_path), total, self.provider.name))

        builder = SubtitleBuilder()
        builder.AddScene(summary=_("Transcription of {}").format(os.path.basename(media_path)))

        transcribed = 0
        chunks_done = 0
        consecutive_failures = 0
        had_failures = False
        max_consecutive = self.settings.get_int('max_consecutive_failures', 3) or 3
        self.total_cost = 0.0
        incomplete_error : SubtitleError|None = None
        try:
            for done, chunk in enumerate(chunks):
                if self.aborted or client.aborted:
                    # Keep everything transcribed so far: abandoning billed
                    # work would be worse than partial results.
                    logging.warning(_("Transcription cancelled after {done}/{total} chunks").format(
                        done=done, total=total))
                    had_failures = True
                    break

                if progress_cb:
                    progress_cb(done, total, self._span_label(chunk))

                try:
                    segment = self._transcribe_chunk(client, media_path, chunk)
                except SubtitleError as e:
                    had_failures = True
                    self.last_error = e
                    consecutive_failures += 1
                    # Two failures before anything ever worked is a systemic
                    # problem (credentials, model, endpoint): fail fast with
                    # the real error instead of grinding through every chunk.
                    limit = 2 if transcribed == 0 else max_consecutive
                    if consecutive_failures >= limit:
                        incomplete_error = SubtitleError(
                            _("Transcription blocked after {count} consecutive chunk failures: {error}").format(
                                count=consecutive_failures, error=e),
                            error=e)
                        if transcribed == 0:
                            self.status = TranscriptionStatus.FAILED
                            raise incomplete_error
                        logging.error(str(incomplete_error))
                        break
                    logging.warning(_("Skipping chunk {}: {}").format(self._span_label(chunk), e))
                    chunks_done += 1
                else:
                    chunks_done += 1
                    if segment is not None:
                        consecutive_failures = 0
                        for line in self._lines_for_segment(segment):
                            builder.BuildLine(line.start, line.end, line.text,
                                              {'speaker': line.speaker} if line.speaker else None)
                            transcribed += 1
                            if segment_cb:
                                segment_cb(line)
        finally:
            self._active_client = None

        if transcribed == 0:
            self.status = TranscriptionStatus.FAILED
            raise SubtitleError(_("No timed subtitles could be produced from {}").format(media_path))

        logging.info(_("Transcribed {} lines from {} chunks").format(transcribed, chunks_done))
        if self.total_cost > 0:
            logging.info(_("Transcription cost: ${:.4f}").format(self.total_cost))
        subtitles = builder.Build()
        subtitles.sourcepath = os.path.normpath(media_path)
        subtitles.file_format = '.srt'
        self.partial_subtitles = subtitles
        if incomplete_error is not None:
            self.last_error = incomplete_error
        self.status = (TranscriptionStatus.INCOMPLETE if incomplete_error is not None or had_failures
                       else TranscriptionStatus.COMPLETED)
        return subtitles

    def CreateTranscriptionProject(self, media_path : str, options : Options|None = None,
                                   progress_cb : TranscriptionProgressCallback|None = None,
                                   segment_cb : TranscriptionSegmentCallback|None = None) -> SubtitleProject:
        """
        Transcribe media and return a project ready for the translation workflow.
        """
        subtitles = self.TranscribeMedia(media_path, progress_cb, segment_cb)

        project = SubtitleProject(persistent=bool(options and options.use_project_file))
        project.subtitles = subtitles
        project.projectfile = project.GetProjectFilepath(media_path)

        if options is not None:
            project.UpdateProjectSettings(SettingsType(options))
            # One "Post-process transcription" toggle covers both cleanup
            # steps: they both run after transcription, before translation.
            if options.get_bool('postprocess_transcription', True):
                self._preprocess_transcription(subtitles, options)
            batch_subtitles(
                subtitles,
                scene_threshold=options.get_float('scene_threshold') or 60.0,
                min_batch_size=options.get_int('min_batch_size') or 1,
                max_batch_size=options.get_int('max_batch_size') or 100,
                prevent_overlap=options.get_bool('prevent_overlapping_times'),
                min_gap=options.get_float('min_gap', 0.05) or 0.0,
            )
            outputpath = GetOutputPath(media_path, options.get_str('target_language'), '.srt')
            if outputpath:
                subtitles.outputpath = outputpath

            if options.get_bool('postprocess_transcription', True):
                self._postprocess_transcription(subtitles, options)
            self._validate_transcription(subtitles, options)

        return project

    def Abort(self) -> None:
        """Stop transcription after the current chunk."""
        self.aborted = True
        if self._active_client is not None:
            self._active_client.AbortTranscription()

    def _preprocess_transcription(self, subtitles : Subtitles, options : Options) -> None:
        """
        Run the standard preprocessing (dialog splits, duration-based line
        splitting) so transcribed lines obey the same settings as loaded
        files. Runs before batching, like the file-load path. Governed by
        the "Post-process transcription" toggle alongside postprocessing:
        in this context both are just cleanup steps after transcription.
        """
        if subtitles.originals:
            processor = SubtitleProcessor(SettingsType(options))
            processed = processor.PreprocessSubtitles(subtitles.originals)
            # Cleanup can empty every line (filler-only utterances): keep the
            # originals so batching still runs, the postprocess filter removes
            # the empties afterwards instead of crashing batch_subtitles.
            if processed:
                subtitles.originals = processed

    def _postprocess_transcription(self, subtitles : Subtitles, options : Options) -> None:
        """
        Clean transcribed lines (dashes, filler words, line breaks)
        Text-only: timings untouched.
        """
        processor = SubtitleProcessor(SettingsType(options))
        for scene in subtitles.scenes:
            for batch in scene.batches:
                # Cleanup can remove an entire filler-only utterance. Empty
                # translations are allowed by the processor, but source lines
                # must contain text before entering the project/view model.
                batch.originals[:] = [line for line in processor.PostprocessSubtitles(batch.originals)
                                      if line.text and line.text.strip()]
        # Re-derive the flat line list: batches hold the edited copies now
        subtitles.originals, subtitles.translated, dummy = UnbatchScenes(subtitles.scenes)  # type: ignore[unused-ignore]

    def _validate_transcription(self, subtitles : Subtitles, options : Options) -> None:
        """
        Attach source validation notes to fresh batches and tag them for
        revalidation, so hand-edits recompute (and clear) notes via the
        standard ValidateBatch path instead of going stale.
        """
        validator = SubtitleValidator(options)
        for scene in subtitles.scenes:
            for batch in scene.batches:
                batch.validate_originals = True
                notes = validator.ValidateOriginals(batch.originals, self.max_line_seconds)
                batch.errors = list(batch.errors or []) + notes  # type: ignore[assignment]

    def _transcribe_chunk(self, client : TranscriptionClient, media_path : str, chunk : AudioChunk) -> TranscriptionSegment|None:
        # Backend and read errors propagate: the TranscribeMedia loop counts
        # consecutive failures and aborts blocked runs instead of grinding on.
        audio_bytes = self.extractor.ReadChunkBytes(media_path, chunk.start, chunk.end, self.track_index)

        if self.extractor.IsSilent(audio_bytes, self.silence_skip_db):
            logging.debug(_("Skipping silent chunk {} before requesting").format(self._span_label(chunk)))
            return None

        result = client.TranscribeChunk(audio_bytes, 'wav', self.language)

        if result.cost:
            self.total_cost += result.cost

        text = (result.text or '').strip()
        if not text:
            logging.debug(_("Empty transcription for chunk {}").format(self._span_label(chunk)))
            return None

        return TranscriptionSegment(start=chunk.start, end=chunk.end, text=text,
                                    language=result.language or self.language,
                                    words=result.words, parts=result.parts)

    def _lines_for_segment(self, segment : TranscriptionSegment) -> list[TranscriptionSegment]:
        """
        Turn a transcribed chunk into timed subtitle lines.

        Word timings group into lines; provider sub-segments without word
        timings become rebased lines. A chunk with neither stays one line
        over its true chunk span: coarse but honest, and the text was
        already paid for, so it is kept rather than thrown away.
        """
        if segment.words:
            lines = self._group_words(segment.words, segment)
            return lines or [segment]

        if segment.parts:
            rebased = [self._rebase_part(part, segment) for part in segment.parts if part.text.strip()]
            for line in rebased:
                self._warn_if_overlong(line)
            return rebased or [segment]

        self._warn_if_overlong(segment)
        return [segment]

    def _warn_if_overlong(self, line : TranscriptionSegment) -> bool:
        """
        Flag engine-coarse spans no splitter can break up. Word-timed lines
        are already capped by grouping; over-long lines can only come from
        untimed engine segments, whose boundaries deserve a human glance.
        Returns True when a warning was logged.
        """
        duration = (line.end - line.start).total_seconds()
        if duration > self.max_line_seconds:
            logging.warning(_("Long transcription line ({:.1f}s, no word timings to split it): '{}'").format(
                duration, line.text[:120]))
            return True
        return False

    def _rebase_part(self, part : TranscriptionSegment, segment : TranscriptionSegment) -> TranscriptionSegment:
        """
        Rebase a chunk-relative sub-segment onto absolute media time.
        """
        start = segment.start + part.start
        end = segment.start + part.end
        if end <= start:
            end = start + timedelta(seconds=_MIN_LINE_SECONDS)
        if end > segment.end:
            end = segment.end
        if part.confidence is not None and part.confidence < 0.4:
            logging.info(_("Chunk {}: low-confidence segment ({:.0%} no-speech probability): '{}'").format(
                self._span_label(segment), 1.0 - part.confidence, part.text[:120]))
        return TranscriptionSegment(start=start, end=end, text=part.text.strip(),
                                    speaker=part.speaker or segment.speaker,
                                    language=part.language or segment.language,
                                    confidence=part.confidence)

    def _group_words(self, words : list[WordTiming], segment : TranscriptionSegment) -> list[TranscriptionSegment]:
        """
        Group chunk-relative word timings into subtitle lines. Every
        boundary and timing derives from aligned words: max characters,
        max duration, sentence punctuation and real inter-word pauses.
        Offsets are rebased onto the chunk start for absolute timings.
        """
        lines : list[TranscriptionSegment] = []
        current : list[WordTiming] = []

        def flush() -> None:
            if not current:
                return
            text = self._join_words([w.text for w in current])
            start = segment.start + current[0].start
            end = segment.start + current[-1].end
            if end <= start:
                end = start + timedelta(seconds=_MIN_LINE_SECONDS)
            if end > segment.end:
                end = segment.end
            speaker = current[0].speaker or segment.speaker
            lines.append(TranscriptionSegment(start=start, end=end, text=text,
                                              speaker=speaker, language=segment.language))

        def speaker_changed(word : WordTiming) -> bool:
            if not current or word.speaker is None:
                return False
            first = current[0].speaker
            return first is not None and word.speaker != first

        for word in words:
            if current:
                previous = current[-1]
                gap = (word.start - previous.end).total_seconds()
                candidate = self._join_words([w.text for w in current] + [word.text])
                line_seconds = (word.end - current[0].start).total_seconds()
                if (len(candidate) > self.max_line_chars
                        or line_seconds > self.max_line_seconds
                        or gap >= self.word_gap_split
                        or speaker_changed(word)
                        or (previous.text and previous.text[-1] in _SENTENCE_END_CHARS)):
                    flush()
                    current = []
            current.append(word)

        flush()
        return self._merge_slivers(lines)

    def _join_words(self, words : list[str]) -> str:
        """
        Join aligned units, spacing latin words but not CJK characters.
        """
        text = ""
        for word in words:
            if text and _needs_space(text[-1], word[:1]):
                text += " "
            text += word

        return text.strip()

    def _merge_slivers(self, lines : list[TranscriptionSegment]) -> list[TranscriptionSegment]:
        """
        Fold sub-second lines into their neighbour, but never across a real
        pause: a short interjection after seconds of silence is its own line,
        not a span covering the silence. Bounds stay truthful either way.
        """
        if len(lines) < 2:
            return lines

        def close_enough(first : TranscriptionSegment, second : TranscriptionSegment) -> bool:
            """Whether two lines are close enough in time to fold together."""
            return (second.start - first.end).total_seconds() < self.word_gap_split

        merged : list[TranscriptionSegment] = []

        def merge_text(previous : TranscriptionSegment, current : TranscriptionSegment,
                       cross_speaker : bool) -> str:
            if not cross_speaker:
                return self._join_words([previous.text, current.text])
            prefix = previous.text if previous.text.startswith('- ') else f'- {previous.text}'
            return f"{prefix}\n- {current.text}"

        for line in lines:
            if (merged
                    and (line.end - line.start).total_seconds() < _MIN_LINE_SECONDS
                    and close_enough(merged[-1], line)):
                previous = merged[-1]
                cross_speaker = (previous.speaker is not None
                                 and line.speaker is not None
                                 and previous.speaker != line.speaker)
                mixed_dialogue = cross_speaker or (previous.speaker is None
                                                   and previous.text.startswith('- ')
                                                   and '\n' in previous.text)
                merged_text = merge_text(previous, line, mixed_dialogue)
                merged[-1] = TranscriptionSegment(
                    start=previous.start, end=line.end,
                    text=merged_text,
                    speaker=None if mixed_dialogue else previous.speaker or line.speaker,
                    language=previous.language or line.language)
            else:
                merged.append(line)

        if len(merged) >= 2:
            last = merged[-1]
            if ((last.end - last.start).total_seconds() < _MIN_LINE_SECONDS
                    and close_enough(merged[-2], last)):
                previous = merged[-2]
                cross_speaker = (previous.speaker is not None
                                 and last.speaker is not None
                                 and previous.speaker != last.speaker)
                mixed_dialogue = cross_speaker or (previous.speaker is None
                                                   and previous.text.startswith('- ')
                                                   and '\n' in previous.text)
                merged[-2] = TranscriptionSegment(
                    start=previous.start, end=last.end,
                    text=merge_text(previous, last, mixed_dialogue),
                    speaker=None if mixed_dialogue else previous.speaker or last.speaker,
                    language=previous.language or last.language)
                merged.pop()

        if len(merged) >= 2:
            first = merged[0]
            if ((first.end - first.start).total_seconds() < _MIN_LINE_SECONDS
                    and close_enough(first, merged[1])):
                nxt = merged[1]
                cross_speaker = (first.speaker is not None
                                 and nxt.speaker is not None
                                 and first.speaker != nxt.speaker)
                mixed_dialogue = cross_speaker or (first.speaker is None
                                                   and first.text.startswith('- ')
                                                   and '\n' in first.text)
                merged[1] = TranscriptionSegment(
                    start=first.start, end=nxt.end,
                    text=merge_text(first, nxt, mixed_dialogue),
                    speaker=None if mixed_dialogue else first.speaker or nxt.speaker,
                    language=first.language or nxt.language)
                merged.pop(0)

        return merged

    def _span_label(self, span : AudioChunk|TranscriptionSegment) -> str:
        start = span.start.total_seconds()
        end = span.end.total_seconds()
        return f"{start:.1f}s-{end:.1f}s"


class AudioTrackInfo:
    """
    Lightweight audio track descriptor for UI pickers and CLI listing.
    """
    def __init__(self, index : int, codec : str|None = None, language : str|None = None):
        self.index : int = index
        self.codec : str|None = codec
        self.language : str|None = language

    def __str__(self) -> str:
        """Human-readable track label."""
        parts = [f"Track {self.index}"]
        if self.codec:
            parts.append(str(self.codec))
        if self.language:
            parts.append(str(self.language))
        return " - ".join(parts)

    def __repr__(self) -> str:
        return f"AudioTrackInfo(index={self.index}, codec={self.codec!r}, language={self.language!r})"
