import regex

from PySubtrans.Helpers.Parse import ParseKeyValuePairs

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

def ExtractTagDict(tagname : str, text : str) -> tuple[str, dict[str,str]]:
    """
    Look for an xml-like tag in the input text, and extract the contents as a dict of 'key::value' pairs, one per line.
    """
    text, tag = ExtractTag(tagname, text)
    return text, ParseKeyValuePairs(tag)

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
