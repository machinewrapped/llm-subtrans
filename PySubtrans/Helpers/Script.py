import unicodedata
from collections import Counter

import regex

# Scripts whose characters run together without spaces, plus CJK punctuation and
# fullwidth forms. Hangul is deliberately excluded - Korean is space-separated.
CJK_BOUNDARY = regex.compile(r'[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\u3000-\u303f\uff00-\uffef]')

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

# Spanish opening marks, which Unicode classes as other punctuation rather than opening punctuation
INVERTED_OPENING_MARKS = '¿¡'

def NeedsSpace(previous : str, current : str) -> bool:
    """
    Whether a space is needed between two adjacent word tokens.

    Handles Latin scripts (space between words), CJK (no space between
    ideographs), and punctuation (no space before closing marks or after
    opening ones, including Spanish ¿ and ¡). Straight quotes use parity to distinguish open/close.

    Examples: ['Hello', 'world'] -> 'Hello world'
              ['你好', '世界']   -> '你好世界'
              ['He', 'said', '"Hello"'] -> 'He said "Hello"'
    """
    if not previous or not current or previous[-1].isspace() or current[0].isspace():
        return False

    last = previous[-1]
    first = current[0]
    if CJK_BOUNDARY.fullmatch(last) and CJK_BOUNDARY.fullmatch(first):
        return False

    last_category = unicodedata.category(last)
    first_category = unicodedata.category(first)
    # Straight quotes need the accumulated text to distinguish opening/closing.
    if first == '"':
        if previous.count('"') % 2:
            return False
    elif first_category.startswith('P') and first_category not in ('Ps', 'Pi') and first not in INVERTED_OPENING_MARKS:
        return False

    if last in "'-\u2019" or last_category in ('Ps', 'Pi') or last in INVERTED_OPENING_MARKS:
        return False
    if last == '"':
        return previous.count('"') % 2 == 0
    return True

def JoinWords(words : list[str]) -> str:
    """Join aligned word tokens with language-appropriate spacing."""
    text = ""
    for word in words:
        if NeedsSpace(text, word):
            text += " "
        text += word
    return text.strip()

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
