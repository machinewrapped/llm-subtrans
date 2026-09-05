from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import timedelta

import regex

from PySubtrans import batch_subtitles
from PySubtrans.Helpers import GetOutputPath
from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleBuilder import SubtitleBuilder
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.Subtitles import Subtitles
from PySubtrans.Transcription.AudioExtractor import AudioExtractor, SceneChunk, SceneChunker, CheckFfmpegAvailable
from PySubtrans.Transcription.TranscriptionAligner import WordTiming
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionSegment

# Sentence-ending punctuation across CJK and latin scripts
_SENTENCE_END_CHARS = frozenset('。！？!?\n…')

# Word characters that take spacing on both sides (latin alphanumerics)
_SPACED_CHAR = regex.compile(r'[A-Za-z0-9]')


def _needs_space(previous : str, current : str) -> bool:
    """
    Whether a space belongs between two adjacent aligned units.
    """
    return bool(previous and current
                and _SPACED_CHAR.match(previous)
                and _SPACED_CHAR.match(current))

# Lines shorter than this merge into their neighbour (bounds stay truthful)
_MIN_LINE_SECONDS = 0.4

# Signature for transcription progress callbacks: (chunks_done, chunk_total)
TranscriptionProgressCallback = Callable[[int, int], None]

# Signature for per-scene callbacks: invoked with each transcribed segment
TranscriptionSegmentCallback = Callable[[TranscriptionSegment], None]


class TranscriptionCoordinator:
    """
    End-to-end media to subtitles transcription.

    Extracts coherent audio scenes from a media file, transcribes each
    scene with the provider client, and assembles timestamped subtitles.
    Has no GUI dependencies so CLI and library callers can use it directly.
    """
    def __init__(self, provider : TranscriptionProvider, settings : SettingsType|Options|None = None):
        self.provider : TranscriptionProvider = provider
        self.settings : SettingsType = SettingsType(settings or {})
        self.aborted : bool = False

        chunk_settings = SettingsType({
            'min_chunk_seconds': self.settings.get_float('min_chunk_seconds', 4.0),
            'max_chunk_seconds': self.settings.get_float('max_chunk_seconds', 60.0),
            'silence_min_duration': self.settings.get_float('silence_min_duration', 0.8),
        })
        self.chunker : SceneChunker = SceneChunker(chunk_settings)
        self.extractor : AudioExtractor = self.chunker.extractor
        self._active_client : TranscriptionClient|None = None

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

    @classmethod
    def ResolveProviderSettings(cls, provider_name : str, settings : SettingsType|Options, options : Options|None = None) -> SettingsType:
        """
        Merge settings with shared API keys from Options.provider_settings.

        A transcription provider reuses the stored key of its translation
        counterpart (e.g. OpenRouter) when it has none of its own, so users
        configure one key per vendor instead of one per capability.
        """
        resolved = SettingsType(settings or {})
        if options is not None and isinstance(options, Options):
            # Membership check first: provider_settings raises KeyError for
            # unknown providers and missing keys are the expected case here.
            if provider_name in options.provider_settings:
                shared = options.provider_settings[provider_name]
                for key in ('api_key', 'server_address', 'proxy'):
                    if not resolved.get(key) and shared.get(key):
                        resolved[key] = shared.get(key)

        return resolved

    def CheckRequirements(self, media_path : str) -> list[AudioTrackInfo]:
        """
        Verify ffmpeg availability and return the media audio tracks.
        """
        CheckFfmpegAvailable()
        tracks = self.extractor.ListAudioTracks(media_path)
        return [AudioTrackInfo(index=t.index, codec=t.codec, language=t.language) for t in tracks]

    def PlanScenes(self, media_path : str) -> list[SceneChunk]:
        """
        Return the transcription scene plan without extracting audio.
        """
        return self.chunker.PlanScenes(media_path, self.track_index)

    def TranscribeMedia(self, media_path : str, progress_cb : TranscriptionProgressCallback|None = None,
                        segment_cb : TranscriptionSegmentCallback|None = None) -> Subtitles:
        """
        Transcribe a media file into timestamped subtitles.
        """
        if not media_path or not os.path.isfile(media_path):
            raise SubtitleError(_("Media file not found: {}").format(media_path))

        client : TranscriptionClient = self.provider.GetTranscriptionClient(self.settings)
        self._active_client = client
        chunks = self.chunker.PlanScenes(media_path, self.track_index)
        total = len(chunks)
        logging.info(_("Transcribing {} in {} scenes with {}").format(
            os.path.basename(media_path), total, self.provider.name))

        builder = SubtitleBuilder()
        builder.AddScene(summary=_("Transcription of {}").format(os.path.basename(media_path)))

        transcribed = 0
        scenes_done = 0
        try:
            for done, chunk in enumerate(chunks):
                if self.aborted or client.aborted:
                    raise SubtitleError(_("Transcription aborted"))

                segment = self._transcribe_scene(client, media_path, chunk)
                scenes_done += 1
                if segment is not None:
                    for line in self._lines_for_segment(segment):
                        builder.BuildLine(line.start, line.end, line.text,
                                          {'speaker': line.speaker} if line.speaker else None)
                        transcribed += 1
                        if segment_cb:
                            segment_cb(line)

                if progress_cb:
                    progress_cb(done + 1, total)
        finally:
            self._active_client = None

        if transcribed == 0:
            raise SubtitleError(_("No speech was transcribed from {}").format(media_path))

        logging.info(_("Transcribed {} lines from {} scenes").format(transcribed, scenes_done))
        subtitles = builder.Build()
        subtitles.sourcepath = os.path.normpath(media_path)
        subtitles.file_format = '.srt'
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

        return project

    def Abort(self) -> None:
        """Stop transcription after the current chunk."""
        self.aborted = True
        if self._active_client is not None:
            self._active_client.AbortTranscription()

    def _transcribe_scene(self, client : TranscriptionClient, media_path : str, chunk : SceneChunk) -> TranscriptionSegment|None:
        try:
            audio_bytes = self.extractor.ReadChunkBytes(media_path, chunk.start, chunk.end, self.track_index)
        except SubtitleError as e:
            logging.warning(_("Skipping scene {}: {}").format(self._span_label(chunk), e))
            return None

        try:
            result = client.TranscribeChunk(audio_bytes, 'wav', self.language)
        except SubtitleError as e:
            logging.warning(_("Skipping scene {}: {}").format(self._span_label(chunk), e))
            return None

        text = (result.text or '').strip()
        if not text:
            logging.debug(_("Empty transcription for scene {}").format(self._span_label(chunk)))
            return None

        return TranscriptionSegment(start=chunk.start, end=chunk.end, text=text,
                                    language=result.language or self.language,
                                    words=result.words)

    def _lines_for_segment(self, segment : TranscriptionSegment) -> list[TranscriptionSegment]:
        """
        Turn a transcribed scene into timed subtitle lines.

        Word timings travel with the segment when the engine provides them
        (local ASR with timestamps) and are grouped into lines. Otherwise
        the scene stays one truthful line: timings are never estimated.
        """
        if segment.words:
            lines = self._group_words(segment.words, segment)
            return lines or [segment]

        return [segment]

    def _group_words(self, words : list[WordTiming], segment : TranscriptionSegment) -> list[TranscriptionSegment]:
        """
        Group chunk-relative word timings into subtitle lines. Every
        boundary and timing derives from aligned words: max characters,
        max duration, sentence punctuation and real inter-word pauses.
        Offsets are rebased onto the scene start for absolute timings.
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
            lines.append(TranscriptionSegment(start=start, end=end, text=text,
                                              speaker=segment.speaker, language=segment.language))

        for word in words:
            if current:
                previous = current[-1]
                gap = (word.start - previous.end).total_seconds()
                candidate = self._join_words([w.text for w in current] + [word.text])
                line_seconds = (word.end - current[0].start).total_seconds()
                if (len(candidate) > self.max_line_chars
                        or line_seconds > self.max_line_seconds
                        or gap >= self.word_gap_split
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
        Fold sub-second lines into their neighbour. Bounds stay truthful:
        the merged line simply spans both words.
        """
        if len(lines) < 2:
            return lines

        merged : list[TranscriptionSegment] = []
        for line in lines:
            if merged and (line.end - line.start).total_seconds() < _MIN_LINE_SECONDS:
                previous = merged[-1]
                merged[-1] = TranscriptionSegment(
                    start=previous.start, end=line.end,
                    text=self._join_words([previous.text, line.text]),
                    speaker=previous.speaker or line.speaker,
                    language=previous.language or line.language)
            else:
                merged.append(line)

        if len(merged) >= 2:
            last = merged[-1]
            if (last.end - last.start).total_seconds() < _MIN_LINE_SECONDS:
                previous = merged[-2]
                merged[-2] = TranscriptionSegment(
                    start=previous.start, end=last.end,
                    text=self._join_words([previous.text, last.text]),
                    speaker=previous.speaker or last.speaker,
                    language=previous.language or last.language)
                merged.pop()

        if len(merged) >= 2:
            first = merged[0]
            if (first.end - first.start).total_seconds() < _MIN_LINE_SECONDS:
                nxt = merged[1]
                merged[1] = TranscriptionSegment(
                    start=first.start, end=nxt.end,
                    text=self._join_words([first.text, nxt.text]),
                    speaker=first.speaker or nxt.speaker,
                    language=first.language or nxt.language)
                merged.pop(0)

        return merged

    def _span_label(self, chunk : SceneChunk) -> str:
        start = chunk.start.total_seconds()
        end = chunk.end.total_seconds()
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
