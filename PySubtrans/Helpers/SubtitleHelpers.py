from datetime import timedelta
import logging
from typing import Any
import regex

from PySubtrans.Helpers.Localization import _
from PySubtrans.SubtitleLine import SubtitleLine

_whitespace_collapse = regex.compile("\n\n+")

def AddOrUpdateLine(lines : list[SubtitleLine], line : SubtitleLine) -> int|None:
    """
    Insert a line into a list of lines at the correct position, or replace any existing line.
    """
    if not lines or line.number > lines[-1].number:
        lines.append(line)
        return len(lines) - 1

    for i, item in enumerate(lines):
        if item.number == line.number:
            lines[i] = line
            return i

        if item.number > line.number:
            lines.insert(i, line)
            return i

    return None

def MergeSubtitles(merged_lines : list[SubtitleLine]) -> SubtitleLine:
    """
    Merge multiple lines into a single line with the same start and end times.
    """
    if not merged_lines:
        raise ValueError("No lines to merge")

    if len(merged_lines) < 2:
        return merged_lines[0]

    first_line : SubtitleLine = merged_lines[0]
    last_line : SubtitleLine = merged_lines[-1]
    merged_number : int = first_line.number or 1
    merged_start : timedelta = first_line.start or timedelta(seconds=0)
    merged_end : timedelta = last_line.end or timedelta(seconds=0)
    merged_content : str = "\n".join(line.text or "Missing text" for line in merged_lines)
    merged_translation : str = "\n".join(line.translation for line in merged_lines if line.translation)
    merged_original : str = "\n".join(line.original for line in merged_lines if line.original)
    
    # Create merged SubtitleLine directly
    merged_line = SubtitleLine.Construct(
        number = merged_number,
        start = merged_start,
        end = merged_end,
        text = merged_content,
        metadata = first_line.metadata
    )
    merged_line.translation = merged_translation.strip()
    merged_line.original = merged_original.strip()
    return merged_line

def MergeTranslations(lines : list[SubtitleLine], translated : list[SubtitleLine]) -> list[SubtitleLine]:
    """
    Replace lines with corresponding lines in translated
    """
    line_dict : dict[int|str, SubtitleLine] = {item.key: item for item in lines if item.key}

    for item in translated:
        line_dict[item.key] = item

    out_lines : list[SubtitleLine] = sorted(line_dict.values(), key=lambda item: item.key)

    return out_lines

def ResyncTranslatedLines(original_lines : list[SubtitleLine], translated_lines : list[SubtitleLine]):
    """
    Copy number, start and end from original lines to matching translated lines.
    """
    num_original : int = len(original_lines)
    num_translated : int = len(translated_lines)
    min_lines : int = min(num_original, num_translated)

    for i in range(min_lines):
        translated_lines[i].start = original_lines[i].start or timedelta(seconds=0)
        translated_lines[i].end = original_lines[i].end or timedelta(seconds=0)
        translated_lines[i].number = original_lines[i].number or i + 1

    if num_original < num_translated:
        logging.warning(f"Number of translated lines exceeds the number of original lines. "
                        f"Removed {num_translated - num_original} extra translated lines.")
        del translated_lines[num_original:]

    elif num_original > num_translated:
        logging.warning(f"Number of lines in original and translated subtitles don't match. Synced {min_lines} lines.")

def FindSplitPoint(line: SubtitleLine, split_sequences: list[regex.Pattern[Any]], min_duration: timedelta, min_split_chars: int) -> int|None:
    """
    Find the optimal split point for a subtitle.

    The criteria are:
    Take break sequences as priority order, find the first matching sequence.
    Break at the occurence that is as close to the middle as possible.
    Neither side of the split should be shorter than the minimum line duration
    """
    line_length : int = len(line.text or "")
    start_index : int = min_split_chars
    end_index : int = line_length - min_split_chars
    if end_index <= start_index:
        return None

    middle_index = line_length // 2

    for priority, seq in enumerate(split_sequences, start=0):
        matches : list[regex.Match[Any]] = list(seq.finditer(line.text)) if line.text else []
        if not matches:
            continue

        # Find the match that is closest to the middle of the text
        best_match = min(matches, key=lambda m: abs(m.end() - middle_index))
        split_index = best_match.end()
        if split_index < start_index or split_index > end_index:
            continue

        split_time = GetProportionalDuration(line, split_index, min_duration)

        # Skip if the split is too close to the start or end (exception for newlines)
        if split_time < min_duration or (line.duration - split_time) < min_duration:
            if priority > 0:
                continue

        return split_index

    return None

def GetProportionalDuration(line : SubtitleLine, num_characters : int, min_duration : timedelta|None = None) -> timedelta:
    """
    Calculate the proportional duration of a character string as a percentage of a subtitle
    """
    line_duration = line.duration.total_seconds()
    line_length = len(line.text or "")

    if num_characters > line_length:
        raise ValueError("Proportion is longer than original line")

    length_ratio = num_characters / line_length
    length_seconds = line_duration * length_ratio

    if min_duration:
        length_seconds = max(length_seconds, min_duration.total_seconds())

    return timedelta(seconds=length_seconds)

