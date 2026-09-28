import unicodedata
import regex

_non_word_pattern = regex.compile(r'[^\w\s-]')
_whitespace_run_pattern = regex.compile(r'\s+')

def SanitiseForFilename(text : str) -> str:
    """
    Sanitise a string for use as a filename component.

    Strips non-word characters (preserving Unicode letters, digits, underscores
    and hyphens), collapses whitespace runs to hyphens, and lowercases.
    """
    sanitised = _non_word_pattern.sub('', text).strip().lower()
    return _whitespace_run_pattern.sub('-', sanitised)

whitespace_and_punctuation_pattern = regex.compile(r'[\p{P}\p{Z}\p{C}]')

whitespace_pattern = regex.compile(r'\s+')

def RemoveWhitespaceAndPunctuation(string) -> str:
    """
    Remove all whitespace and punctuation from a string
    """
    # Matches any punctuation, separator, or other Unicode character
    stripped = whitespace_and_punctuation_pattern.sub('', string)

    # Normalize Unicode characters to their canonical forms
    normalized = unicodedata.normalize('NFC', stripped)

    return normalized

def CompressWhitespace(text : str) -> str:
    """
    Collapse runs of whitespace into a single space.
    """
    return whitespace_pattern.sub(' ', text)

def IsTextContentEqual(string1 : str|None, string2 : str|None) -> bool:
    """
    Compare two strings for equality, ignoring whitespace and punctuation
    """
    if string1 and string2:
        stripped1 = RemoveWhitespaceAndPunctuation(string1)
        stripped2 = RemoveWhitespaceAndPunctuation(string2)
        return stripped1 == stripped2

    return string1 == string2

def Linearise(lines : str|list[str]) -> str:
    """
    Ensure that the input is a single string
    """
    if not isinstance(lines, list):
        lines = str(lines).split("\n")

    lines = [ str(line).strip() for line in lines ]
    return " | ".join(lines)

def CompactText(text : str) -> str:
    """Text with all whitespace removed, for comparing transcripts that space words differently."""
    return ''.join(text.split())

def CutText(text : str, lengths : list[int]) -> list[str]:
    """Cut text into pieces holding the given numbers of non-whitespace characters, the last taking the remainder."""
    pieces : list[str] = []
    position = 0

    for length in lengths[:-1]:
        seen = 0
        end = position
        while end < len(text) and seen < length:
            if not text[end].isspace():
                seen += 1
            end += 1

        pieces.append(text[position:end].strip())
        position = end

    pieces.append(text[position:].strip())
    return pieces

def ConvertWhitespaceBlocksToNewlines(text : str) -> str:
    """
    Convert blocks of 3 or more spaces or chinese commas to newlines, unless the text contains newlines already
    """
    if text and '\n' not in text:
        text = regex.sub(r' {3,}|\，\s*', '\n', text)

    return text
