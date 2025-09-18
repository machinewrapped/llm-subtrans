import logging
from typing import Any
import regex
from datetime import timedelta

from PySubtrans.Helpers.SubtitleHelpers import FindSplitPoint, GetProportionalDuration
from PySubtrans.Helpers.Text import (
    dialog_marker,
    split_sequences,
    break_sequences,
    sentence_end_punctuation,
    BreakLongLine,
    BreakDialogOnOneLine,
    CompileDialogSplitPattern,
    CompileFillerWordsPattern,
    ConvertWhitespaceBlocksToNewlines,
    ConvertWideDashesToStandardDashes,
    EnsureFullWidthPunctuation,
    NormaliseDialogTags,
    RemoveFillerWords
)
from PySubtrans.Options import SettingsType
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleLine import SubtitleLine

class SubtitleProcessor:
    """
    Helper class to pre-process or post-process subtitles to make them suitable for translation.

    Will split long lines, add line breaks and remove empty lines.
    """
    def __init__(self, settings : SettingsType):
        # Convert plain dict to SettingsType if needed for typed access
        if isinstance(settings, dict) and not isinstance(settings, SettingsType):
            settings = SettingsType(settings)
            
        self.dialog_marker = dialog_marker
        self.split_sequences = split_sequences
        self.break_sequences = break_sequences
        self._compiled_split_sequences = None
        self._compiled_break_sequences = None
        self.forbidden_start_end_pairs = [
            ("<", ">"),
            ("[", "]"),
            ("(", ")"),
            ('"', '"'),
            ("“", "”"),
            ("‘", "’"),
        ]

        self.max_line_duration : timedelta = settings.get_timedelta('max_line_duration', timedelta(seconds=0))
        self.min_line_duration : timedelta = settings.get_timedelta('min_line_duration', timedelta(seconds=0))
        self.merge_line_duration : timedelta = settings.get_timedelta('merge_line_duration', timedelta(seconds=0))
        self.min_gap : timedelta = settings.get_timedelta('min_gap', timedelta(seconds=0.05))
        self.min_split_chars : int = settings.get_int('min_split_chars') or 4

        self.convert_whitespace_to_linebreak : bool = settings.get_bool('whitespaces_to_newline', False)
        self.break_dialog_on_one_line : bool = settings.get_bool('break_dialog_on_one_line', False)
        self.normalise_dialog_tags : bool = settings.get_bool('normalise_dialog_tags', False)
        self.remove_filler_words : bool = settings.get_bool('remove_filler_words', False)
        self.full_width_punctuation : bool = settings.get_bool('full_width_punctuation', False)
        self.convert_wide_dashes : bool = settings.get_bool('convert_wide_dashes', False)

        self.break_long_lines : bool = settings.get_bool('break_long_lines', False)
        self.max_single_line_length : int = settings.get_int('max_single_line_length') or 40
        self.min_single_line_length : int = settings.get_int('min_single_line_length') or 4

        self.split_dialog_pattern: regex.Pattern[Any]|None = CompileDialogSplitPattern(self.dialog_marker) if self.break_dialog_on_one_line else None

        filler_words = settings.get_list('filler_words', [])
        self.filler_words_pattern: regex.Pattern[Any]|None = CompileFillerWordsPattern(filler_words) if self.remove_filler_words else None

        self.split_by_duration: bool = self.max_line_duration.total_seconds() > 0.0

    def PreprocessSubtitles(self, lines : list[SubtitleLine]) -> list[SubtitleLine]:
        """
        Pre-process subtitles to make them suitable for translation.

        Will split long lines, add line breaks to dialog, and remove empty lines.
        """
        if not lines:
            return []

        processed : list[SubtitleLine] = []
        line_number : int = lines[0].number

        if self.merge_line_duration.total_seconds() > 0.0:
            lines = self._merge_short_lines(lines, self.merge_line_duration)

        for line in lines:
            line.number = line_number
            self._preprocess_line(line)
            if not line.text:
                continue

            needs_split : bool = self.split_by_duration and line.duration > self.max_line_duration

            if needs_split:
                split_lines = self._split_line_by_duration(line)

                processed.extend(split_lines)
                line_number += len(split_lines)

                if len(split_lines) > 1:
                    new_line_text = ''.join([str(l) for l in split_lines])
                    logging.debug(f"Split line {line.number} into {len(split_lines)} parts:\n{str(line)}-->\n{new_line_text}")
                else:
                    logging.debug(f"Failed to split line {line.number}:\n{str(line)}")
            else:
                processed.append(line)
                line_number += 1

        return processed

    def PostprocessSubtitles(self, lines : list[SubtitleLine]) -> list[SubtitleLine]:
        """
        Post-process lines after translation
        """
        if not lines:
            return []

        processed : list[SubtitleLine] = []

        for line in lines:
            processed_line = self._postprocess_line(line)
            if processed_line:
                processed.append(processed_line)

        # TODO: fix minimum durations
        # TODO: fix overlapping start/end times (or merge the lines?)

        return processed

    def _preprocess_line(self, line : SubtitleLine):
        """
        Split dialogs onto separate lines.
        Adjust line breaks to split at punctuation weighted by centrality
        """
        text : str = line.text.strip() if line.text else ""
        if not text:
            return

        # Convert whitespace blocks to newlines
        if self.convert_whitespace_to_linebreak:
            text = ConvertWhitespaceBlocksToNewlines(text)

        # Convert wide dashes to standard dashes
        if self.convert_wide_dashes:
            text = ConvertWideDashesToStandardDashes(text)

        # Ensure full-width punctuation is used in Asian languages
        if self.full_width_punctuation:
            text = EnsureFullWidthPunctuation(text)

        # Remove filler words
        if self.remove_filler_words and self.filler_words_pattern:
            text = RemoveFillerWords(text, self.filler_words_pattern)

        # If the subtitle is a single line, see if it should have line breaks added
        if self.break_dialog_on_one_line and self.split_dialog_pattern:
            text = BreakDialogOnOneLine(text, self.split_dialog_pattern)

        # If the subtitle has multiple lines, make sure dialog markers match
        if self.normalise_dialog_tags:
            text = NormaliseDialogTags(text, self.dialog_marker)

        if text != line.text:
            logging.debug(f"Preprocessed line {line.number}:\n{line.text}\n-->\n{text}")
            line.text = text

    def _postprocess_line(self, line : SubtitleLine):
        """
        Split dialogs onto separate lines.
        Normalise dialog markers.
        Add line breaks to long lines.
        """
        text = line.text.strip() if line.text else ""

        if not text:
            return line

        if self.remove_filler_words and self.filler_words_pattern:
            text = RemoveFillerWords(text, self.filler_words_pattern)

        if self.convert_wide_dashes:
            text = ConvertWideDashesToStandardDashes(text)

        if self.break_dialog_on_one_line and self.split_dialog_pattern:
            text = BreakDialogOnOneLine(text, self.split_dialog_pattern)

        if self.normalise_dialog_tags:
            text = NormaliseDialogTags(text, self.dialog_marker)

        if self.full_width_punctuation:
            text = EnsureFullWidthPunctuation(text)

        if self.break_long_lines:
            text = self._break_long_lines(text)

        if text == line.text:
            return line

        logging.debug(f"Postprocessed line {line.number}:\n{line.text}\n-->\n{text}")
        processed_line = SubtitleLine.Construct(line.number, line.start, line.end, text, line.metadata)
        return processed_line

    def _break_long_lines(self, text : str) -> str:
        """
        Add line breaks to long lines
        """
        if self._compiled_break_sequences is None:
            self._compile_break_sequences()

        max_length = self.max_single_line_length
        min_length = self.min_single_line_length
        break_sequences = self._compiled_break_sequences
        if break_sequences:
            text = BreakLongLine(text, max_line_length=max_length, min_line_length=min_length, break_sequences=break_sequences)
        return text

    def _split_line_by_duration(self, line: SubtitleLine) -> list[SubtitleLine]:
        """
        Recursively split a line into smaller lines based on the duration of the text,
        by choosing a split point from the defined sequences weighted towards the middle.
        """
        result : list[SubtitleLine] = []
        stack : list[SubtitleLine] = [line]

        if self._compiled_split_sequences is None:
            self._compile_split_sequences()
            if not self._compiled_split_sequences:
                raise ValueError("No split sequences defined for splitting lines by duration.")

        while stack:
            current_line = stack.pop()
            if not current_line or not current_line.text or not current_line.start or not current_line.end:
                continue

            if current_line.duration <= self.max_line_duration or len(current_line.text) < self.min_split_chars * 2:
                result.append(current_line)
                continue

            if (current_line.text[0], current_line.text[-1]) in self.forbidden_start_end_pairs:
                result.append(current_line)
                continue

            split_point = FindSplitPoint(current_line, self._compiled_split_sequences, min_duration=self.min_line_duration, min_split_chars=self.min_split_chars)
            if split_point is None:
                result.append(current_line)
                continue

            split_text : str = current_line.text[split_point:].strip()
            split_duration : timedelta = GetProportionalDuration(current_line, len(split_text), self.min_line_duration)
            split_start : timedelta = current_line.end - split_duration
            split_end : timedelta = current_line.end

            new_line = SubtitleLine.Construct(current_line.number, current_line.start, split_start - self.min_gap, current_line.text[:split_point], current_line.metadata)
            split_line = SubtitleLine.Construct(current_line.number, split_start, split_end, split_text, current_line.metadata)

            stack.extend([split_line, new_line])

        for i, result_line in enumerate(result, start=0):
            result_line.number = line.number + i

        return result

    def _merge_short_lines(self, lines : list[SubtitleLine], short_duration : timedelta) -> list[SubtitleLine]:
        """
        Merge lines with very short durations into the previous line
        """
        if not lines:
            return []

        merged_lines : list[SubtitleLine] = []
        current_line : SubtitleLine = lines[0]

        for line in lines[1:]:
            if not current_line.text_normalized:
                current_line = line
                continue

            if line.duration < short_duration:
                # If the line ends with a sentence-ending punctuation mark, assume different speakers (questionable logic)
                if current_line.text_normalized[-1] in sentence_end_punctuation:
                    current_line.text = f"{dialog_marker}{current_line.text}\n{dialog_marker}{line.text}"
                else:
                    current_line.text = f"{current_line.text}\n{line.text}"

                current_line.end = line.end
            else:
                merged_lines.append(current_line)
                current_line = line

        merged_lines.append(current_line)
        return merged_lines

    def _compile_split_sequences(self):
        self._compiled_split_sequences = [regex.compile(seq) for seq in self.split_sequences]

    def _compile_break_sequences(self):
        self._compiled_break_sequences = [regex.compile(seq) for seq in self.break_sequences]


