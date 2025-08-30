from datetime import timedelta
import logging
from typing import Any
import regex

from PySubtitle.Instructions import DEFAULT_TASK_TYPE
from PySubtitle.Options import Options
from PySubtitle.Helpers.Subtitles import MergeTranslations
from PySubtitle.Helpers.Text import IsTextContentEqual
from PySubtitle.SubtitleLine import SubtitleLine
from PySubtitle.SubtitleError import NoTranslationError, TranslationError, UntranslatedLinesError
from PySubtitle.SubtitleValidator import SubtitleValidator
from PySubtitle.Translation import Translation

default_pattern = (
    r"#(?P<number>\d+)"
    r"(?:[\s\r\n]+Original>[\s\r\n]+(?P<original>[\s\S]*?))?"
    r"[\s\r\n]+Translation>"
    r"(?:[\s\r\n]?(?P<body>[\s\S]*?))?"
    r"(?=\n#\d|\Z)"
)

fallback_patterns = [
    r"#(?P<number>\d+)(?:[\s\r\n]+Original>[\s\r\n]+(?P<original>[\s\S]*?))?[\s\r\n]*(?:Translation>(?:[\s\r\n]+(?P<body>[\s\S]*?))?(?:(?=\n{2,})|\Z))",
    r"#(?P<number>\d+)(?:[\s\r\n]+Original[>:][\s\r\n]+(?P<original>[\s\S]*?))?[\s\r\n]*(?:Translation[>:](?:[\s\r\n]+(?P<body>[\s\S]*?))?(?:(?=\n{2,})|\Z))",
    r"#(?P<number>\d+)(?:[\s\r\n]+Original[>:][\s\r\n]+(?P<original>[\s\S]*?))?[\s\r\n]*Translation[>:][\s\r\n]+(?P<body>[\s\S]*?)(?=(?:\n{2,}#)|\Z)",
    r"#(?P<number>\d+)(?:[\s\r\n]*Original[>:][\s\r\n]*(?P<original>[\s\S]*?))?[\s\r\n]*Translation[>:][\s\r\n]*(?P<body>[\s\S]*?)(?=(?:\n{2,}#)|\Z)",
    r"#(?P<number>\d+)[\s\r\n]+Translation[>:][\s\r\n]+(?P<body>[\s\S]*?)(?=(?:\n{2,}#)|\Z)",
    r"#(?P<number>\d+)(?:[\s\r\n]+(?P<body>[\s\S]*?))?(?:(?=\n{2,})|\Z)"  # Just the number and translation
    ]

class TranslationParser:
    """
    Extract translated subtitles from the AI translation response
    """
    def __init__(self, task_type : str, options : Options):
        self.options : Options = options
        self.text : str|None = None
        self.translations : dict[int|str, SubtitleLine] = {}
        self.translated : list[SubtitleLine] = []
        self.errors : list[Exception] = []
        self.metatags : list[str] = ["summary", "scene"]
        self.task_type : str = task_type
        self.regex_patterns : list[regex.Pattern[Any]] = self.GetRegularExpressionPatterns(task_type)

    def GetRegularExpressionPatterns(self, task_type : str = DEFAULT_TASK_TYPE) -> list[regex.Pattern[Any]]:
        """
        Returns a list of regular expressions to try for extracting translations
        """
        # Use the current default pattern, and fall back on alternative/older patterns if no matches are found
        patterns = [
            regex.compile(
                pattern.replace(DEFAULT_TASK_TYPE, task_type), regex.MULTILINE) for pattern in [default_pattern] + fallback_patterns
            ]
        return patterns

    def ProcessTranslation(self, translation : Translation) -> list[SubtitleLine]|None:
        """
        Extract lines from a batched translation, using the
        pre-defined pattern to match each line, or a list of fallbacks
        if the match fails.
        """
        self.text = translation.text if isinstance(translation, Translation) else str(translation)

        if not self.text:
            raise TranslationError("No translated text provided", translation=translation)

        matches : list[dict[str,str]] = []

        for template in self.regex_patterns:
            matches = self.FindMatches(f"{self.text}\n\n", template)

            if matches:
                break

        if not matches:
            raise TranslationError(f"No matches found in translation text using patterns: {self.regex_patterns}", translation=translation)

        logging.debug(f"Matches: {str(matches)}")

        subs = [SubtitleLine(match) for match in matches]
        self.translations = {
            sub.key: sub for sub in subs
            }

        if not self.translations:
            return None

        self.translated = MergeTranslations(self.translated, list(self.translations.values()))

        self.errors = self.ValidateTranslations()

        if self.errors and self.translated:
            self._fix_unclosed_tags()
            self.errors = self.ValidateTranslations()

        return self.translated

    def FindMatches(self, text, template) -> list[dict[str,str]]:
        """
        re.findall has some very unhelpful behaviour, so we use finditer instead.
        """
        return [{
            'body': match.group('body'),
            'number': match.groupdict().get('number'),
            'start': match.groupdict().get('start'),
            'end': match.groupdict().get('end'),
            'original': match.groupdict().get('original')
            } for match in template.finditer(text)]

    def MatchTranslations(self, originals : list[SubtitleLine]) -> tuple[list[SubtitleLine], list[SubtitleLine]]:
        """
        Match lines in the translation with the original subtitles
        """
        if not originals:
            raise ValueError("Original subtitles not provided")

        matched = []
        unmatched = []

        for item in originals:
            translation = self.translations.get(item.key)
            if translation:
                translation.number = item.number
                translation.start = item.start or timedelta(seconds=0)
                translation.end = item.end or timedelta(seconds=0)

                if translation.original and IsTextContentEqual(translation.text, item.text):
                    # Check for swapped original & translation
                    translation.text = translation.original
                    translation.original = item.text

                item.translation = translation.text
                matched.append(translation)

            else:
                item.translation = None
                unmatched.append(item)

        if unmatched:
            self.TryFuzzyMatches(unmatched)

        if unmatched:
            self.errors.append(UntranslatedLinesError(f"No translation found for {len(unmatched)} lines", lines=unmatched))

        return matched, unmatched

    def TryFuzzyMatches(self, unmatched : list [SubtitleLine]) -> None:
        """
        Try to match translations to their source lines using heuristics
        """
        possible_matches : list[tuple[SubtitleLine,SubtitleLine]] = []
        for item in (item for item in unmatched if item.number is not None):
            for translation in self.translations.values():
                if translation.original:
                    if IsTextContentEqual(translation.original, item.text):
                        # A match on the original text is pretty compelling
                        possible_matches.append((item, translation))
                        continue
                    elif IsTextContentEqual(translation.text, item.text):
                        # LLMs sometimes swap the original and translated text - swap them back
                        translation.text = translation.original
                        translation.original = item.text
                        possible_matches.append((item, translation))
                        continue

                    #TODO: check for merged lines

        if possible_matches:
            for item, translation in possible_matches:
                logging.warning(f"Found fuzzy match for line {item.number} in translations")
                item.translation = f"#Fuzzy: {translation.text}"
                #unmatched.remove(item)

    def ValidateTranslations(self) -> list[Exception]:
        """
        Check if the translation seems at least plausible
        """
        if not self.translated:
            return [ NoTranslationError("Failed to extract translations from response", translation=self.text) ]

        validator = SubtitleValidator(self.options)
        return validator.ValidateTranslations(self.translated)

    def _fix_unclosed_tags(self):
        """
        Check if the last line of the translation picked up a summary without a closing tag
        """
        last_line : SubtitleLine = self.translated[-1]

        if not last_line.text:
            return

        # Use a regex to check for opening metatags and ensure there is a matching close tag. If not, truncate the text at the tag.
        re_opening = regex.compile(rf"<({'|'.join(self.metatags)})>", regex.IGNORECASE)

        for match in re_opening.finditer(last_line.text):
            tag = match.group(1)
            if not regex.search(rf"</{tag}>", last_line.text):
                logging.warning(f"Found unclosed tag {tag} in translation: {tag}")
                last_line.text = last_line.text[:match.start()]
                break
            