import logging
from typing import Any
import regex
from enum import Enum

from PySubtrans.Helpers import GetValueFromName

class Substitutions:
    """
    Helper class to perform textual substitutions based on a dictionary of (before,after) pairs.
    """
    class Mode(Enum):
        Auto = 0
        WholeWords = 1
        PartialWords = 2

        def serialize(self):
            return self.name

    template_wholewords = r"\b{}\b"
    template_partialwords = r"{}"
    template_automatic = r"(?<!\p{{Script=Latin}}){}(?!\p{{Script=Latin}})"

    def __init__(self, substitutions : dict|list|str, mode : Mode|str = Mode.Auto):
        self._patterns = None
        self._mode = self._parse_mode(mode)
        self.substitutions = substitutions

    @property
    def mode(self) -> Mode:
        return self._mode

    @mode.setter
    def mode(self, mode : Mode|int|str):
        self._mode = self._parse_mode(mode)
        self._patterns = None

    @property
    def substitutions(self) -> dict:
        return self._substitutions

    @substitutions.setter
    def substitutions(self, substitutions : dict|list|str):
        self._substitutions = Substitutions.Parse(substitutions) if substitutions else {}
        self._patterns = None

    @property
    def patterns(self) -> list[tuple[regex.Pattern[Any], str]]:
        if self._patterns is None:
            self._patterns = self._compile_patterns()
        return self._patterns

    def PerformSubstitutions(self, input : list|str):
        """
        Try to substitute all (before,after) pairs in an input string

        :param input: string to perform substitutions on.
        :return: a string with the substitutions performed.
        """
        result = str(input)
        for pattern, substitution in self.patterns:
            result = pattern.sub(substitution, result)

        return result

    def PerformSubstitutionsOnAll(self, input : list[str]) -> tuple[list[str], dict[str,str]]:
        """
        Try to substitute all (before,after) pairs in a list of strings.

        :param input: list of strings to perform substitutions on.
        :return: a list of strings with the substitutions performed, along with a dictionary of (before,after) pairs for each element that had substitutions.
        """
        result = [ self.PerformSubstitutions(line) for line in input ]
        replacements = { line: new_line for line, new_line in zip(input, result) if new_line != str(line) }
        return result, replacements

    def _compile_patterns(self) -> list[tuple[regex.Pattern[Any], str]]:
        patterns = []
        template = self._get_template()

        for before, after in self.substitutions.items():
            substitution = template.format(regex.escape(before))
            pattern = regex.compile(substitution, flags=regex.UNICODE)
            patterns.append((pattern, after))

        return patterns

    def _get_template(self):
        if self.mode == Substitutions.Mode.WholeWords:
            return self.template_wholewords
        elif self.mode == Substitutions.Mode.PartialWords:
            return self.template_partialwords
        else:
            return self.template_automatic

    def _parse_mode(self, mode):
        if isinstance(mode, self.Mode):
            return mode

        if isinstance(mode, int):
            try:
                return self.Mode(mode)
            except ValueError:
                raise ValueError(f"No enum member for value: {mode}")

        return GetValueFromName(mode, list(self.Mode))

    @classmethod
    def Parse(cls, sub_list : str|list|dict|Any, separator="::") -> dict:
        """
        Parse a list of (before,after) pairs from a string, dictionary or list of strings, or a file containing such pairs.

        :param sub_list: is assumed to be a list of (before,after) pairs separated by the separator ("::" by default).

        :return: a dictionary of (before,after) pairs
        """
        if not sub_list:
            return {}

        if isinstance(sub_list, dict):
            return sub_list

        if isinstance(sub_list, str):
            sub_list = regex.split("[\n,]", sub_list)

        if isinstance(sub_list, list):
            substitutions = {}
            for sub in sub_list:
                if "::" in sub:
                    before, after = sub.split(separator)
                    substitutions[before] = after
                elif sub.strip():
                    try:
                        with open(sub, "r", encoding="utf-8", newline='') as f:
                            for line in [line.strip() for line in f if line.strip()]:
                                if "::" in line:
                                    before, after = line.split("::")
                                    substitutions[before] = after
                                else:
                                    raise ValueError(f"Invalid substitution format in {sub}: {line}")

                    except FileNotFoundError:
                        logging.warning(f"Substitution file not found: {sub}")
                    except ValueError:
                        raise

            return substitutions

        return {}