import regex

dialog_marker = "- "
emdash = "—"

def ConvertWideDashesToStandardDashes(text : str) -> str:
    """
    Replace em dashes with standard dialog dashes
    """
    text = regex.sub(r'\s*—+\s*', ' - ', text)
    return text

def CompileDialogSplitPattern(dialog_marker):
    """
    Compile a regex pattern to split lines at dialog markers.
    A marker only counts after punctuation, so a stutter dash attached to a word ("你- 你", "what- what") never splits.
    After a hyphen it needs whitespace too, so the second dash of "--" is not taken for a marker.
    """
    escaped_marker = regex.escape(dialog_marker)
    re_split = r"(?:(?<=[^\p{L}\p{N}\s-])\s*|(?<=-)\s+)(?=" + escaped_marker + ")"
    return regex.compile(re_split)

def BreakDialogOnOneLine(text : str, dialog_marker : str|regex.Pattern) -> str:
    """
    Break dialog into separate lines
    """
    # Split line at dialog markers following any non-alphanumeric character and whitespace
    # This should catch the majority of genuine dialog markers and few other uses of a dash
    # Uses a look-behind followed by a look-ahead so that the split point is not consumed
    if not isinstance(dialog_marker, regex.Pattern):
        dialog_marker = CompileDialogSplitPattern(dialog_marker)

    line_parts = dialog_marker.split(text)

    if len(line_parts) > 1:
        text = '\n'.join([part.strip() for part in line_parts])

    return text

def NormaliseDialogTags(text : str, dialog_marker : str) -> str:
    """
    Make sure dialog markers are consistent across lines
    """
    if not dialog_marker in text:
        return text

    line_parts = text.split('\n')

    # If a single line starts with a dialog marker, remove it
    if len(line_parts) == 1 and text.startswith(dialog_marker):
        return text[len(dialog_marker):].strip()

    # If any of the line parts starts with a dialog marker, they all should
    if any(part.startswith(dialog_marker) for part in line_parts):
        line_parts = [part if part.startswith(dialog_marker) else dialog_marker + part for part in line_parts]
        text = '\n'.join(part.strip() for part in line_parts)

    return text

def RemoveEmptyDialogRows(text : str, dialog_marker : str) -> str:
    """
    Drop rows left holding nothing but a dialog marker, e.g. after filler removal emptied an utterance.
    """
    bare_marker = dialog_marker.strip()
    if not bare_marker or bare_marker not in text:
        return text

    rows = [row for row in text.split('\n') if row.strip() not in ('', bare_marker)]
    return '\n'.join(rows)
