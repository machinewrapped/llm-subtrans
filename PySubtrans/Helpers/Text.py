from typing import Any
import unicodedata
import regex
import unicodedata
from collections import Counter

common_punctuation = r"[.,!?;:…¡¿]"
sentence_end_punctuation = r"[.!?…？！。﹑]"

dialog_marker = "- "
emdash = "—"

standard_filler_words = "um,umm,uh,uhh,er,err,ah,ahh,oh,eh,hm,hmm,hmmm,huh,ha,mmm,ow,oww"

whitespace_and_punctuation_pattern = regex.compile(r'[\p{P}\p{Z}\p{C}]')

priority_break_sequences = [
    regex.escape(dialog_marker),  # Dialog marker
    r"(?=\([^)]*\)|\[[^\]]*\])",  # Look ahead to find a complete parenthetical or bracketed block to split before
    r"(?=\"[^\"]*\")",  # Look ahead to find a complete block within double quotation marks
    r"(?=<([ib])>[^<]*</\1>)",  # Look ahead to find a block in italics or bold
]

break_sequences = priority_break_sequences + [
    r"[.!?](\s|\")",  # End of sentence punctuation like '!', '?', possibly at the end of a quote
    r"[？！。…，、﹑]", # Full-width punctuation (does not need to be followed by whitespace)
    r"[,](\s|\")",  # Commas followed by whitespace or quote
    r"[:;]\s+",  # Colon and semicolon
    r"[–—]+\s+",  # Dashes
    r"\s+",  # Whitespace
]

split_sequences = [
    r"\n",  # Newline has the highest priority
    regex.escape(dialog_marker),  # Dialog marker
    r"(?=\([^)]*\)|\[[^\]]*\])",  # Look ahead to find a complete parenthetical or bracketed block to split before
    r"(?=\"[^\"]*\")",  # Look ahead to find a complete block within double quotation marks
    r"(?=<([ib])>[^<]*</\1>)",  # Look ahead to find a block in italics or bold
    r"[.!?](\s|\")",  # End of sentence punctuation like '!', '?', possibly at the end of a quote
    r"[？！。…，、﹑]", # Full-width punctuation (does not need to be followed by whitespace)
    r"[,](\s|\")",  # Commas followed by whitespace or quote
    r"[:;；：]\s+",  # Colon and semicolon
    r"[–—]+\s+",  # Dashes
    r" {3,}"  # Three or more spaces
]

# Dictionary mapping half-width punctuation to full-width
fullwidth_punctuation_map = {
    ',': '，',
    '.': '。',
    ';': '；',
    ':': '：',
    '?': '？',
    '!': '！'
}

# Regex to find half-width punctuation adjacent to Asian script characters
fullwidth_pattern = r'(?<=[\p{Script=Han}\p{Script=Hangul}\p{Script=Hiragana}\p{Script=Katakana}])(?P<punct>[,.;:?!\-])(?=[\p{Script=Han}\p{Script=Hangul}\p{Script=Hiragana}\p{Script=Katakana}])'

def RemoveWhitespaceAndPunctuation(string) -> str:
    """
    Remove all whitespace and punctuation from a string
    """
    # Matches any punctuation, separator, or other Unicode character
    stripped = whitespace_and_punctuation_pattern.sub('', string)

    # Normalize Unicode characters to their canonical forms
    normalized = unicodedata.normalize('NFC', stripped)

    return normalized

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

def ConvertWhitespaceBlocksToNewlines(text : str) -> str:
    """
    Convert blocks of 3 or more spaces or chinese commas to newlines, unless the text contains newlines already
    """
    if text and '\n' not in text:
        text = regex.sub(r' {3,}|\，\s*', '\n', text)

    return text

def ConvertWideDashesToStandardDashes(text : str) -> str:
    """
    """
    text = regex.sub(r'\s*—+\s*', ' - ', text)
    return text

def EnsureFullWidthPunctuation(text: str) -> str:
    """
    Ensure full-width punctuation is used in East Asian languages by replacing half-width
    punctuation with full-width equivalents only when directly adjacent to Asian script characters.
    """
    # Function to replace each punctuation mark found with its full-width counterpart
    def replace(match):
        punctuation = match.group('punct')
        return fullwidth_punctuation_map[punctuation]

    # Replace all occurrences of half-width punctuation in the text
    return regex.sub(fullwidth_pattern, replace, text)


def CompileDialogSplitPattern(dialog_marker):
    """
    Compile a regex pattern to split lines at dialog markers
    """
    escaped_marker = regex.escape(dialog_marker)
    re_split = r"(?<=[^a-zA-Z0-9\s])\s*(?=" + escaped_marker + ")"
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

def FindBreakPoint(text : str, break_sequences: list[regex.Pattern], max_line_length : int, min_line_length : int) -> int|None:
    """
    Find the optimal break point for a long line
    """
    line_length = len(text)
    start_index = min_line_length
    end_index = line_length - min_line_length
    if end_index <= start_index:
        return None

    middle_index = line_length // 2

    min_break = min(line_length - max_line_length, max_line_length)
    min_break = max(min_break, min_line_length)

    for priority, seq in enumerate(break_sequences, start=1):
        matches = list(seq.finditer(text))
        if not matches:
            continue

        # Find the match that is closest to the middle of the text
        best_match = min(matches, key=lambda m: abs(m.end() - middle_index))
        split_index = best_match.end()
        if split_index < start_index or split_index > end_index:
            continue

        # Don't break if it would result in a line longer than the maximum or shorter than the minimum, if avoidable
        if priority > len(priority_break_sequences) and split_index < min_break:
            continue

        return split_index

    return None

def BreakLongLine(text : str, max_line_length : int, min_line_length : int, break_sequences: list[regex.Pattern]) -> str:
    """
    Add line breaks to long single lines
    """
    length = len(text)
    if length <= max_line_length:
        return text

    if '\n' in text:
        return text

    break_index = FindBreakPoint(text, break_sequences, max_line_length, min_line_length)
    if break_index:
        text = text[:break_index].strip() + '\n' + text[break_index:].strip()

    return text

def LimitTextLength(text : str, max_length : int) -> str:
    """
    Limit the length of a text string to a maximum number of characters, cutting at the nearest sentence end or whitespace
    """
    text = text.strip()

    if len(text) <= max_length:
        return text

    pattern = r'\.|\?|!'
    matches = [(m.start(), m.group()) for m in regex.finditer(pattern, text)]

    # Find the closest match to the max length, if any
    for position, match in reversed(matches): # type: ignore
        if position <= max_length:
            return text[:position + 1]

    # If no sentence end is found within the limit, cut at the nearest whitespace
    nearest_space = text.rfind(' ', 0, max_length)
    if nearest_space != -1:
        return text[:nearest_space] + '...'
    else:
        # As a last resort, cut directly at the max length
        return text[:max_length] + '...'

def CompileFillerWordsPattern(filler_words: str|list[str]) -> regex.Pattern[Any]|None:
    """
    Compile a regex pattern to match any provided filler word, assuming they are
    followed by mandatory punctuation and possibly preceded by punctuation.
    """
    if isinstance(filler_words, str):
        filler_words = [i.strip() for i in filler_words.split(',') if i.strip()]

    if not filler_words:
        return None

    filler_pattern = '|'.join(regex.escape(i) for i in filler_words if i)
    filler_words_pattern = rf"(^|[,¡¿]?\s+)({filler_pattern})({common_punctuation}+(\s+|$))"

    return regex.compile(filler_words_pattern, flags=regex.IGNORECASE|regex.MULTILINE)

def RemoveFillerWords(text: str, fillerWords: str|list[str]|regex.Pattern[Any]) -> str:
    """
    Remove filler words from a text string, adjusting capitalization based on the capitalization of the filler word.
    """
    fillerPatterns = fillerWords if isinstance(fillerWords, regex.Pattern) else CompileFillerWordsPattern(fillerWords)

    if fillerPatterns is None:
        return text

    output = []
    last_index = 0
    capitalise_first_letter = False

    def _append_previous_section(output : list[str], text : str, previous_start : int, previous_end : int, capitalise_first_letter : bool):
        if previous_end > previous_start:
            if capitalise_first_letter:
                first_letter = text[previous_start].upper()
                next_index = previous_start + 1
                previous_section = first_letter if next_index == previous_end else first_letter + text[next_index:previous_end]
                output.append(previous_section)
            else:
                output.append(text[previous_start:previous_end])

    for match in fillerPatterns.finditer(text):
        start, end = match.span()

        # Output any text before the match
        _append_previous_section(output, text, last_index, start, capitalise_first_letter)

        # Capitalize the first letter of the next section if the filler word was capitalized
        first_alpha = next((char for char in text[start:end] if char.isalpha()), None)
        capitalise_first_letter = first_alpha is not None and first_alpha.isupper()

        last_index = end

    # Append any remaining text after the last match
    if last_index < len(text):
        _append_previous_section(output, text, last_index, len(text), capitalise_first_letter)

    # Join the output sections into a single string
    return ' '.join(output)

def ContainsTags(text : str) -> bool:
    """
    Check if a line contains any html-like tags (<i>, <b>, etc.)
    """
    return regex.search(r"<[^>]+>", text) is not None

def ExtractTag(tagname : str, text : str) -> tuple[str, str|None]:
    """
    Look for an xml-like tag in the input text, and extract the contents.
    """
    if not tagname:
        return text, None

    open_tag = f"<{tagname}>"
    close_tag = f"</{tagname}>"
    empty_tag = f"<{tagname}/>"

    text = text.replace(empty_tag, '')

    end_index = text.rfind(close_tag)

    if end_index == -1:
        return text.strip(), None

    start_index = text.rfind(open_tag, 0, end_index)
    if start_index == -1:
        raise ValueError(f"Malformed {tagname} tags in {text}")

    tag = text[start_index + len(open_tag):end_index].strip()
    text_before = text[:start_index].strip()
    text_after = text[end_index + len(close_tag):].strip()
    text = '\n'.join([text_before, text_after]).strip()

    return text, tag

def ExtractTagList(tagname, text):
    """
    Look for an xml-like tag in the input text, and extract the contents as a comma or newline separated list.
    """
    if text is not None:
        text, tag = ExtractTag(tagname, text)
        tag_list = [ item.strip() for item in regex.split("[\n,]", tag) ] if tag else []
        return text, tag_list
    return text, []

def SanitiseSummary(summary : str, movie_name : str|None = None, max_summary_length : int|None = None):
    """
    Remove trivial parts of summary text and limit the length if required
    """
    if not summary:
        return None

    summary = summary.replace("Summary of the batch", "")
    summary = summary.replace("Summary of the scene", "")
    summary = regex.sub(r'^(?:(?:Scene|Batch)[\s\d:\-]*)+', '', summary, flags=regex.IGNORECASE)

    if movie_name:
        # Remove movie name and any connectors (-,: or whitespace)
        summary = regex.sub(r'^' + regex.escape(movie_name) + r'\s*[:\-\s]*', '', summary)

    summary = regex.sub(r'^[\s\d:\-]*', '', summary, flags=regex.IGNORECASE)

    summary = summary.strip()

    if max_summary_length:
        summary = LimitTextLength(summary, max_summary_length)

    return summary or None

def IsRightToLeftText(text: str) -> bool:
    """
    Check if text is predominantly RTL using Unicode bidirectional properties
    """
    if not text:
        return False
    count = Counter(unicodedata.bidirectional(c) for c in text if not c.isspace())
    rtl_count = sum(count[d] for d in ['R', 'AL', 'RLE', 'RLI'])
    ltr_count = sum(count[d] for d in ['L', 'LRE', 'LRI'])
    return rtl_count > ltr_count
