"""
Developer tool for tuning transcription line assembly.

Replays a capture written by TranscriptionCapture through the line builder,
so the effect of a code or settings change can be seen without transcribing again.

    python scripts/transcribe.py media.mkv --capture capture.json    # transcribe once
    python scripts/replay_transcription.py capture.json
    python scripts/replay_transcription.py capture.json --min-line-duration 1.2
    python scripts/replay_transcription.py capture.json --source words --quiet
    python scripts/replay_transcription.py capture.json --quiet --compare min_line_seconds 0.6 0.8 1.0
    python scripts/replay_transcription.py capture.json --quiet -o replayed.vtt

--source parts strips the words, so it shows parts without splitting.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
from dataclasses import asdict, replace
from datetime import timedelta
from difflib import SequenceMatcher
from typing import Any

import regex

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySubtrans.Helpers.Speech import EstimateSpeechSeconds
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleProcessor import SubtitleProcessor
from PySubtrans.Subtitles import Subtitles
from PySubtrans.Transcription.LineSettings import DEFAULT_TIMING_CORRECTION_FACTOR, LineSettings
from PySubtrans.Transcription.TranscriptionCapture import LoadCapture, LoadCaptureLineSettings, LoadCaptureProvider
from PySubtrans.Transcription.TranscriptionLines import TranscriptionLineBuilder
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.TranscriptionRun import TranscriptionRun
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionSegment
from PySubtrans.Transcription.WordAlignment import WordCoverage


def BuildLines(segments : list[TranscriptionSegment], **overrides) -> list[TranscriptionSegment]:
    """Run the line builder over captured segments with the given settings."""
    options = Options()
    settings = {
        'max_line_chars': options.get_int('max_characters') or 120,
        'max_line_seconds': options.get_float('max_line_duration') or 4.0,
        'min_split_chars': options.get_int('min_split_chars') or 3,
        'min_line_seconds': options.get_float('min_line_duration') or 0.8,
        'max_newlines': options.get_int('max_newlines') or 2,
        'min_gap': options.get_float('min_gap') or 0.05,
    }
    settings.update({key: value for key, value in overrides.items() if value is not None})

    builder = TranscriptionLineBuilder(LineSettings(**settings))

    lines : list[TranscriptionSegment] = []
    for segment in segments:
        lines.extend(builder.LinesForSegment(segment))

    return lines


def ProviderWordCoverage(capture : str) -> WordCoverage:
    """The word coverage of the provider a capture came from, as a transcription run would use it."""
    name = LoadCaptureProvider(capture)
    providers = {key.casefold(): provider for key, provider in TranscriptionProvider.get_providers().items()}
    provider = providers.get(name.casefold()) if name else None
    return provider.word_coverage if provider is not None else WordCoverage.COMPLETE


def ProviderTimingCorrection(capture : str) -> float:
    """The timing correction factor the capture's provider defaults to, for captures that did not record it."""
    name = LoadCaptureProvider(capture)
    if not name:
        return DEFAULT_TIMING_CORRECTION_FACTOR

    try:
        provider = TranscriptionProvider.create_provider(name, SettingsType())
    except ValueError:
        return DEFAULT_TIMING_CORRECTION_FACTOR

    return provider.settings.get_float('timing_correction_factor') or DEFAULT_TIMING_CORRECTION_FACTOR


def SaveLines(lines : list[TranscriptionSegment], path : str, postprocess : bool) -> int:
    """
    Write lines as a subtitle file, the way a transcription run would.
    Mirrors TranscriptionCoordinator._finish_run and _process_transcription.
    """
    run = TranscriptionRun(None)
    for line in lines:
        run.AddLine(line)

    subtitles = Subtitles()
    subtitles.originals = run.lines

    if postprocess and subtitles.originals:
        processor = SubtitleProcessor(SettingsType(Options()))
        processed = processor.PreprocessSubtitles(subtitles.originals)
        subtitles.originals = [line for line in processor.PostprocessSubtitles(processed)
                               if line.text and line.text.strip()]

    subtitles.SaveOriginal(path)
    return subtitles.linecount


def SelectSource(segments : list[TranscriptionSegment], source : str) -> list[TranscriptionSegment]:
    """Strip words or parts so the line builder takes the requested path."""
    if source == 'parts':
        return [replace(segment, words=[]) if segment.parts else segment for segment in segments]
    if source == 'words':
        return [replace(segment, parts=[]) for segment in segments]
    return segments


def Timecode(value : timedelta) -> str:
    """Readable m:ss.mmm for a media offset."""
    total = value.total_seconds()
    return f"{int(total // 60):02d}:{total % 60:06.3f}"


def Describe(segments : list[TranscriptionSegment]) -> None:
    """Print a summary of what the provider gave us."""
    words = sum(len(segment.words) for segment in segments)
    parts = sum(len(segment.parts) for segment in segments)
    speakers = {part.speaker for segment in segments for part in segment.parts if part.speaker}
    speakers |= {word.speaker for segment in segments for word in segment.words if word.speaker}

    print(f"{len(segments)} chunks, {words} word timings, {parts} parts, "
          f"{len(speakers)} speakers{' ' + repr(sorted(speakers)) if speakers else ''}")

    # Words starting before the word ahead of them in the array
    backwards = sum(1 for segment in segments
                    for previous, word in zip(segment.words, segment.words[1:])
                    if word.start < previous.start)
    affected = sum(1 for segment in segments
                   if any(word.start < previous.start for previous, word in zip(segment.words, segment.words[1:])))
    print(f"{backwards} words start before their predecessor, in {affected} chunks")

    # How much of each chunk transcript the word stream reproduces
    ratios = [WordSimilarity(segment) for segment in segments if segment.words and segment.text]
    if ratios:
        print(f"word/transcript similarity: min {min(ratios):.2f}, "
              f"median {statistics.median(ratios):.2f}, max {max(ratios):.2f}")


def WordSimilarity(segment : TranscriptionSegment) -> float:
    """Similarity between the joined word stream and the chunk transcript, ignoring whitespace."""
    words = ''.join(''.join(word.text.split()) for word in segment.words)
    text = ''.join(segment.text.split())
    return SequenceMatcher(None, words, text, autojunk=False).ratio()


def Splittable(line : TranscriptionSegment, min_line_seconds : float) -> bool:
    """
    Whether some row boundary leaves both halves at least min_line_seconds.
    Row timings are gone after merging, so each half's duration is estimated from its share of characters.
    """
    rows = line.text.split('\n')
    total_chars = sum(len(row) for row in rows)
    duration = (line.end - line.start).total_seconds()
    if total_chars == 0:
        return False

    for index in range(1, len(rows)):
        head = sum(len(row) for row in rows[:index]) / total_chars * duration
        if head >= min_line_seconds and duration - head >= min_line_seconds:
            return True

    return False


def SpokenText(text : str) -> str:
    """Text without whitespace or dialogue markers, for counting how much of a transcript survived."""
    return ''.join(regex.sub(r'^- ', '', row) for row in text.split('\n')).replace(' ', '')


def Report(lines : list[TranscriptionSegment], min_line_seconds : float, max_newlines : int, quiet : bool = False,
           transcript_chars : int = 0) -> None:
    """Print each line, flagging the ones worth looking at, and how much of the transcript the lines hold."""
    short = 0
    fast = 0
    stacked = 0
    splittable = 0

    for line in lines:
        duration = (line.end - line.start).total_seconds()
        newlines = line.text.count('\n')
        flags = ''
        if duration < min_line_seconds:
            flags += ' [short]'
            short += 1
        if duration < EstimateSpeechSeconds(line.text):
            flags += ' [fast]'
            fast += 1
        if newlines >= max_newlines:
            flags += f' [{newlines + 1} rows]'
            stacked += 1
            if Splittable(line, min_line_seconds):
                flags += ' [splittable]'
                splittable += 1

        if not quiet:
            text = line.text.replace('\n', ' / ')
            print(f"[{Timecode(line.start)} --> {Timecode(line.end)}] {duration:5.2f}s{flags} {text}")

    print(f"\n{len(lines)} lines, {short} under {min_line_seconds}s, {fast} shorter than their speech estimate, "
          f"{stacked} at the newline limit ({splittable} splittable)")

    if transcript_chars:
        output_chars = sum(len(SpokenText(line.text)) for line in lines)
        print(f"{output_chars} of {transcript_chars} transcript characters in the lines ({output_chars / transcript_chars:.0%})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a captured transcription through the line builder")
    parser.add_argument('capture', help="Capture file written by TranscriptionCapture")
    parser.add_argument('--min-line-duration', type=float, help="Below this a line is a fragment to be merged")
    parser.add_argument('--max-line-duration', type=float, help="Longest a merged line may be")
    parser.add_argument('--max-characters', type=int, help="Longest a merged line may be, in characters")
    parser.add_argument('--max-newlines', type=int, help="Most rows a merged line may have, less one")
    parser.add_argument('--merge-eligible-gap', type=float, help="Widest gap that can be merged across")
    parser.add_argument('--same-speaker-gap', type=float, help="As above, for one speaker continuing")
    parser.add_argument('--no-merge-speakers', action='store_true', help="Keep separate speakers on separate lines")
    parser.add_argument('--timing-correction-factor', type=float,
                        help="Extend lines shorter than this fraction of their speech estimate (default: the capture's)")
    parser.add_argument('--word-coverage', choices=[coverage.value for coverage in WordCoverage],
                        help="How much of the transcript the words spell (default: the capture's)")
    parser.add_argument('--source', choices=('auto', 'parts', 'words'), default='auto',
                        help="Build lines from parts or words (default: whatever the builder prefers)")
    parser.add_argument('--quiet', action='store_true', help="Print only the summary")
    parser.add_argument('-o', '--output', help="Also write the lines as subtitles (format from the extension)")
    parser.add_argument('--no-postprocess', dest='postprocess', action='store_false',
                        help="Write the raw lines, without the post-processing a transcription run applies")
    parser.add_argument('--compare', nargs='+', metavar=('SETTING', 'VALUE'),
                        help="Builder setting and the values to compare, e.g. --compare min_line_seconds 0.6 1.0")
    args = parser.parse_args()

    segments = LoadCapture(args.capture)
    Describe(segments)
    segments = SelectSource(segments, args.source)
    transcript_chars = sum(len(SpokenText(segment.text)) for segment in segments)

    # Settings not given on the command line are the ones the capture's run used.
    # Older captures did not record them, so they fall back to the current options and their provider's defaults.
    recorded = LoadCaptureLineSettings(args.capture)
    if recorded is not None:
        defaults : dict[str, Any] = asdict(recorded)
    else:
        print("Line settings were not recorded in this capture, so the current options and provider defaults are used")
        defaults = {
            'word_coverage': ProviderWordCoverage(args.capture),
            'timing_correction_factor': ProviderTimingCorrection(args.capture),
        }

    overrides : dict[str, Any] = {
        'min_line_seconds': args.min_line_duration,
        'max_line_seconds': args.max_line_duration,
        'max_line_chars': args.max_characters,
        'max_newlines': args.max_newlines,
        'merge_eligible_gap': args.merge_eligible_gap,
        'same_speaker_merge_eligible_gap': args.same_speaker_gap,
        'can_merge_different_speakers': False if args.no_merge_speakers else None,
        'word_coverage': WordCoverage(args.word_coverage) if args.word_coverage else None,
        'timing_correction_factor': args.timing_correction_factor,
    }

    for key, value in defaults.items():
        if overrides.get(key) is None:
            overrides[key] = value

    if args.compare:
        setting, *values = args.compare
        for value in values:
            print(f"\n=== {setting} = {value} ===")
            trial = dict(overrides)
            trial[setting] = float(value) if '.' in value else int(value)
            lines = BuildLines(segments, **trial)
            Report(lines, float(trial.get('min_line_seconds') or 0.8), int(trial.get('max_newlines') or 2), args.quiet,
                   transcript_chars)
        return 0

    print()
    lines = BuildLines(segments, **overrides)
    Report(lines, overrides['min_line_seconds'] or 0.8, overrides['max_newlines'] or 2, args.quiet, transcript_chars)

    if args.output:
        count = SaveLines(lines, args.output, args.postprocess)
        print(f"Saved {count} lines to {args.output}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
