import os

from collections.abc import Iterable
from typing import Any

import regex
from PySubtrans.Helpers.Localization import LocaleDisplayItem
from PySubtrans.Helpers.Text import SanitiseForFilename
from PySubtrans.SubtitleError import SubtitleError

def FormatNumberRanges(numbers : Iterable[int]) -> str:
    """
    Format integer values as a comma-separated list of compact contiguous ranges.

    Duplicate values are removed and values are sorted before formatting. A
    singleton is written as one number, while a run of two or more values is
    written as ``start-end``.
    """
    sorted_numbers = sorted(set(numbers))
    if not sorted_numbers:
        return ""

    ranges : list[str] = []
    range_start = sorted_numbers[0]
    range_end = range_start

    for number in sorted_numbers[1:]:
        if number == range_end + 1:
            range_end = number
            continue

        ranges.append(str(range_start) if range_start == range_end else f"{range_start}-{range_end}")
        range_start = number
        range_end = number

    ranges.append(str(range_start) if range_start == range_end else f"{range_start}-{range_end}")
    return ", ".join(ranges)

def GetValueName(value : Any) -> str:
    """
    Get the name of an object if it has one, or a string representation of the object.
    Then, if the name is in CamelCase, insert spaces between each word.
    """
    if hasattr(value, 'name'):
        name = value.name
        # Insert spaces before all caps in CamelCase (but not at the start)
        spaced_name = regex.sub(r'(?<=[a-z])(?=[A-Z])', ' ', name)
        return spaced_name

    return str(value)

def GetValueFromName(name : str, values : list[Any], default : Any = None) -> Any:
    """
    Get the value from a name in a list of values
    """
    for value in values:
        if str(name) == str(value) or name == GetValueName(value):
            if isinstance(value, LocaleDisplayItem):
                return value.code
            return value

    if default is not None:
        return default

    raise ValueError(f"Value '{name}' not found in {values}")

def UpdateFields(item : dict[str,Any], update : dict[str,Any], fields : list[str]):
    """
    Patch selected fields in a dictionary
    """
    if not isinstance(item, dict) or not isinstance(update, dict):
        raise ValueError(f"Can't patch a {type(item).__name__} with a {type(update).__name__}")

    item.update({field: update[field] for field in update.keys() if field in fields})

def GetInputPath(filepath : str|None) -> str|None:
    """
    Normalize the input file path for cross-platform compatibility.
    
    Args:
        filepath: Input file path
        
    Returns:
        str: Normalized path preserving original extension
        None: If filepath is None
    """
    if not filepath:
        return None
    return os.path.normpath(filepath)

def GetOutputPath(filepath : str|None, language : str|None = None, format_extension : str|None = None) -> str|None:
    """
    Generate output path for subtitle files with proper language suffix and format extension.
    
    Args:
        filepath: Input file path to base output path on
        language: Optional language code to add as suffix
        format_extension: Target format extension (e.g., '.ass', '.srt'). If None, infers from input filepath.
        
    Returns:
        str: Output path with format: "basename.language.extension"
        None: If filepath is None
    """
    if not filepath:
        return None

    # Get directory and basename without extension
    directory = os.path.dirname(filepath)
    basename, current_extension = os.path.splitext(os.path.basename(filepath))

    # Add language suffix (sanitised for use in filenames)
    if language:
        sanitised = SanitiseForFilename(language)
        if sanitised:
            language_suffix = f".{sanitised}"
            if not basename.endswith(language_suffix):
                basename = basename + language_suffix

    # Determine extension
    if not format_extension:
        if current_extension == ".subtrans":
            raise ValueError("Extension must be provided to deduce output path from project file")
        format_extension = current_extension

    if not format_extension.startswith('.'):
        format_extension = f".{format_extension}"

    # Construct final path with proper normalization
    output_path = os.path.join(directory, f"{basename}{format_extension}")
    return os.path.normpath(output_path)

def FormatMessages(messages : list[dict[str,Any]]) -> str:
    lines : list[str] = []
    for index, message in enumerate(messages, start=1):
        lines.append(f"Message {index}")
        if 'role' in message:
            lines.append(f"Role: {message['role']}")
        if 'content' in message:
            if isinstance(message['content'], str):
                content = message['content'].replace('\\n', '\n')
                lines.extend(["--------------------", content])
            elif isinstance(message['content'], dict):
                for key, value in message['content'].items():
                    text = f"{key}: {value}".replace('\\n', '\n')
                    lines.append(text)
        lines.append("")

    return '\n'.join(lines)

def FormatErrorMessages(errors : list[SubtitleError|str]) -> str:
    """
    Extract error messages from a list of errors
    """
    return ", ".join([ error.message or str(error) if isinstance(error, SubtitleError) else str(error) for error in errors ])

def DescribeError(error : BaseException|None) -> str:
    """
    Describe an exception for logging, always naming the exception type.

    Some causes are only identifiable by type - an empty message, or a bare
    decoder message like "Expecting value: line 1 column 1", means nothing
    without knowing what raised it.
    """
    if error is None:
        return ""

    detail = str(error).strip()
    name = type(error).__name__

    return f"{name}: {detail}" if detail else name
