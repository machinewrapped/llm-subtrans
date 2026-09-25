import regex

from PySubtrans.Helpers.Dialog import dialog_marker

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

    fallbacks : list[int] = []

    for priority, seq in enumerate(break_sequences, start=1):
        matches = list(seq.finditer(text))
        if not matches:
            continue

        # Find the match that is closest to the middle of the text
        best_match = min(matches, key=lambda m: abs(m.end() - middle_index))
        split_index = best_match.end()
        if split_index < start_index or split_index > end_index:
            continue

        # Don't break if it would result in a line longer than the maximum or shorter than the minimum, if avoidable.
        # Track the candidate as a fallback rather than discarding it - a break point that is merely unbalanced
        # is still far better than no break point at all.
        if priority > len(priority_break_sequences) and split_index < min_break:
            fallbacks.append(split_index)
            continue

        return split_index

    if fallbacks:
        return min(fallbacks, key=lambda index: abs(index - middle_index))

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
