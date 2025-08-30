import os

from typing import Any

import regex
from PySubtitle.Helpers.Localization import LocaleDisplayItem
from PySubtitle.SubtitleError import SubtitleError

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
    if not filepath:
        return None

    basename, dummy = os.path.splitext(os.path.basename(filepath)) # type: ignore[unused-ignore]
    path = os.path.join(os.path.dirname(filepath), f"{basename}.srt")
    return os.path.normpath(path)

def GetOutputPath(filepath : str|None, language : str|None = None) -> str|None:
    if not filepath:
        return None

    basename, dummy = os.path.splitext(os.path.basename(filepath)) # type: ignore[unused-ignore]

    language = language or "translated"

    language_suffix = f".{language}"
    if not basename.endswith(language_suffix):
        basename = basename + language_suffix

    return os.path.join(os.path.dirname(filepath), f"{basename}.srt")

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