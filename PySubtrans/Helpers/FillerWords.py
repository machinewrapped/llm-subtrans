from typing import Any

import regex

common_punctuation = r"[.,!?;:…¡¿]"

standard_filler_words = "um,umm,uh,uhh,er,err,ah,ahh,oh,eh,hm,hmm,hmmm,huh,ha,mmm,ow,oww"

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
    Each row is processed separately, so a match never swallows a line break, and rows left empty are dropped.
    """
    fillerPatterns = fillerWords if isinstance(fillerWords, regex.Pattern) else CompileFillerWordsPattern(fillerWords)

    if fillerPatterns is None:
        return text

    if '\n' in text:
        rows = text.split('\n')
        cleaned = [RemoveFillerWords(row, fillerPatterns) for row in rows]
        return '\n'.join(row for row, original in zip(cleaned, rows) if row.strip() or not original.strip())

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
