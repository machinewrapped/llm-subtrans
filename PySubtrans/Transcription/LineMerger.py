from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from PySubtrans.Helpers.Script import JoinWords
from PySubtrans.Transcription.LineSettings import LineSettings
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionSegment


def IsDialogue(line : TranscriptionSegment) -> bool:
    """Whether a line already holds more than one dialogue turn."""
    return line.text.startswith('- ') and '\n' in line.text


def SplitEvenly(run : list[TranscriptionSegment], count : int) -> list[list[TranscriptionSegment]]:
    """Divide a run into `count` pieces differing in length by at most one."""
    base, remainder = divmod(len(run), count)
    chunks : list[list[TranscriptionSegment]] = []
    start = 0

    for index in range(count):
        size = base + (1 if index < remainder else 0)
        chunks.append(run[start:start + size])
        start += size

    return chunks


class LineMerger:
    """Merges lines too brief to read into their neighbours, preserving pauses and dialogue turns."""
    def __init__(self, settings : LineSettings):
        self.settings : LineSettings = settings

    def MergeSlivers(self, lines : list[TranscriptionSegment], limit : timedelta|None = None) -> list[TranscriptionSegment]:
        """Merge brief adjacent lines, then extend any still brief into the pause after them, up to `limit` for the last."""
        # Subtitles play in time order whatever order the engine emitted them in, so that is how neighbours are judged
        lines = sorted(lines, key=lambda line: line.start)
        if len(lines) < 2:
            return self._extend_into_pauses(lines, limit)

        merged : list[TranscriptionSegment] = []
        for run in self._sliver_runs(lines):
            merged.extend(self._merge_run(chunk) for chunk in self._balanced_chunks(run))

        return self._extend_into_pauses(merged, limit)

    def _sliver_runs(self, lines : list[TranscriptionSegment]) -> list[list[TranscriptionSegment]]:
        """Group lines into runs that belong together."""
        runs : list[list[TranscriptionSegment]] = [[lines[0]]]

        for line in lines[1:]:
            run = runs[-1]

            # A fragment joins the fragment before it.
            # One left standing alone takes the next line whatever its length, unless it can be extended into a pause instead.
            stranded = len(run) == 1
            takes_fragment = self._is_sliver(line) or (stranded and not self._extends_instead(run[-1], line))

            # Overlapping speech is always shown together.
            # Only the line before counts, so one runaway span cannot draw in everything after it.
            overlaps = line.start < run[-1].end

            if overlaps or (self._is_sliver(run[-1]) and takes_fragment and self._merge_eligible(run, line)):
                run.append(line)
            else:
                runs.append([line])

        return runs

    def _extends_instead(self, fragment : TranscriptionSegment, line : TranscriptionSegment) -> bool:
        """Whether a fragment followed by another speaker's line has room to be extended instead of merged."""
        # A complete turn is better extended into the pause than made into dialogue
        speakers_differ = fragment.speaker is not None and line.speaker is not None and fragment.speaker != line.speaker
        target = fragment.start + timedelta(seconds=self.settings.min_line_seconds)
        return speakers_differ and target <= line.start - timedelta(seconds=self.settings.min_gap)

    def _merge_eligible(self, run : list[TranscriptionSegment], line : TranscriptionSegment) -> bool:
        """Whether a line belongs with a run, by speaker and by the pause before it."""
        # The pause is measured from the end of the run, so its last speaker is the one continued or interrupted
        speaker = run[-1].speaker

        if not self.settings.can_merge_different_speakers and speaker is not None and line.speaker is not None:
            if speaker != line.speaker:
                return False

        end = max(part.end for part in run)
        return (line.start - end).total_seconds() < self.settings.EligibleGap(speaker, line.speaker)

    def _balanced_chunks(self, run : list[TranscriptionSegment]) -> list[list[TranscriptionSegment]]:
        """Divide a run into the fewest even pieces that each read comfortably."""
        if len(run) < 2 or self._chunk_fits(run):
            return [run]

        for count in range(2, len(run)):
            chunks = SplitEvenly(run, count)
            if all(self._chunk_fits(chunk) for chunk in chunks):
                return chunks

        return [[line] for line in run]

    def _chunk_fits(self, chunk : list[TranscriptionSegment]) -> bool:
        """Whether merging a chunk would stay within the limits a line is held to."""
        # Measured rather than predicted: how many turns render as dialogue depends on the order they fold together in
        merged = self._merge_run(chunk)

        if (merged.end - merged.start).total_seconds() > self.settings.max_line_seconds:
            return False

        if len(merged.text) > self.settings.max_line_chars:
            return False

        return merged.text.count('\n') <= self.settings.max_newlines

    def _merge_run(self, run : list[TranscriptionSegment]) -> TranscriptionSegment:
        """Combine a run of lines into one, with a dialogue row per speaker turn."""
        turns : list[list[TranscriptionSegment]] = []
        for line in run:
            if turns and self._same_turn(turns[-1][-1], line):
                turns[-1].append(line)
            else:
                turns.append([line])

        texts = [JoinWords([line.text for line in turn]) for turn in turns]
        dialogue = len(turns) > 1

        if dialogue:
            text = '\n'.join(turn if turn.startswith('- ') else f'- {turn}' for turn in texts)
        else:
            text = texts[0]

        speakers = {line.speaker for line in run if line.speaker is not None}
        return TranscriptionSegment(
            start=min(line.start for line in run), end=max(line.end for line in run), text=text,
            speaker=None if dialogue else (speakers.pop() if speakers else None),
            language=next((line.language for line in run if line.language), None))

    def _same_turn(self, first : TranscriptionSegment, second : TranscriptionSegment) -> bool:
        """Whether two adjacent lines belong to one speaker's turn."""
        if IsDialogue(first) or IsDialogue(second):
            return False

        # Diarization does not tell overlapping voices apart, and markers stop a translator reading two utterances as one sentence
        if second.start < first.end:
            return False

        return first.speaker is None or second.speaker is None or first.speaker == second.speaker

    def _extend_into_pauses(self, lines : list[TranscriptionSegment], limit : timedelta|None) -> list[TranscriptionSegment]:
        """Extend each brief line to the minimum duration where the pause after it allows."""
        min_duration = timedelta(seconds=self.settings.min_line_seconds)
        min_gap = timedelta(seconds=self.settings.min_gap)

        extended : list[TranscriptionSegment] = []
        for index, line in enumerate(lines):
            following = lines[index + 1].start - min_gap if index + 1 < len(lines) else limit
            target = line.start + min_duration

            # Only the end moves, so a subtitle never appears before its speech
            if self._is_sliver(line) and following is not None and target <= following:
                line = replace(line, end=target)

            extended.append(line)

        return extended

    def _is_sliver(self, line : TranscriptionSegment) -> bool:
        """Whether a line is too brief to read."""
        return (line.end - line.start).total_seconds() < self.settings.min_line_seconds
