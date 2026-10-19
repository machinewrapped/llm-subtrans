from enum import Enum
from typing import Any, ClassVar

from PySubtrans.SubtitleError import TranslationError

class ValidationSeverity(Enum):
    """
    How serious a validation issue is.
    Errors mean the translation needs another attempt.
    Warnings flag lines worth a human glance, without blocking completion.
    """
    Error = "Error"
    Warning = "Warning"

class TranslationValidationError(TranslationError):
    """
    A problem found by validating translated or transcribed lines.
    Records the affected line numbers so they survive a project save and reload.
    """
    severity : ValidationSeverity = ValidationSeverity.Error
    _types_by_name : ClassVar[dict[str, type['TranslationValidationError']]] = {}

    def __init__(self, message : str, lines : list[Any]|None = None, translation : Any|None = None, line_numbers : list[int]|None = None):
        super().__init__(message, translation)
        self.lines = lines or []
        self.line_numbers : list[int] = line_numbers or [line.number for line in self.lines if getattr(line, 'number', None)]

    def __init_subclass__(cls, **kwargs : Any) -> None:
        """
        Register every validation error type by name, so saved issues can be rebuilt with their severity.
        """
        super().__init_subclass__(**kwargs)
        TranslationValidationError._types_by_name[cls.__name__] = cls

    @property
    def is_warning(self) -> bool:
        return self.severity == ValidationSeverity.Warning

    @staticmethod
    def GetTypeByName(name : str) -> type['TranslationValidationError']|None:
        """ Find the validation error type with the given class name """
        if name == TranslationValidationError.__name__:
            return TranslationValidationError

        return TranslationValidationError._types_by_name.get(name)

class UntranslatedLinesError(TranslationValidationError):
    pass

class UnmatchedLinesError(TranslationValidationError):
    pass

class EmptyLinesError(TranslationValidationError):
    pass

class TooManyNewlinesError(TranslationValidationError):
    severity = ValidationSeverity.Warning

class LineTooLongError(TranslationValidationError):
    severity = ValidationSeverity.Warning

class ExcessiveDurationError(TranslationValidationError):
    severity = ValidationSeverity.Warning

def IsValidationWarning(error : Any) -> bool:
    """ Check whether an error is a validation issue with warning severity """
    return isinstance(error, TranslationValidationError) and error.is_warning
