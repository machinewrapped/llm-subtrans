from typing import Any

from PySubtrans.Helpers.Localization import _

class SubtitleError(Exception):
    def __init__(self, message : str|None = None, error : Exception|None = None):
        super().__init__(message)
        self.error = error
        self.message = message

    def __str__(self) -> str:
        if self.error:
            return str(self.error)
        elif self.message:
            return self.message
        return super().__str__()

class NoProviderError(SubtitleError):
    def __init__(self):
        super().__init__(_("Provider not specified in options"))

class ProviderError(SubtitleError):
    def __init__(self, message : str|None = None, provider : Any = None):
        super().__init__(message)
        self.provider = provider
 
class ProviderConfigurationError(ProviderError):
    def __init__(self, message : str, provider : Any, error : Exception|None = None):
        super().__init__(message, provider)
        self.error = error

class TranslationError(SubtitleError):
    def __init__(self, message : str, translation : Any = None, error : Exception|None = None):
        super().__init__(message)
        self.translation = translation
        self.error = error

class TranslationAbortedError(TranslationError):
    def __init__(self):
        super().__init__(_("Translation aborted"))

class TranslationImpossibleError(TranslationError):
    """ No chance of retry succeeding """
    def __init__(self, message : str, error : Exception|None = None):
        super().__init__(message, error)

class TranslationResponseError(TranslationError):
    def __init__(self, message : str, response : Any):
        super().__init__(message)
        self.response = response

class NoTranslationError(TranslationError):
    def __init__(self, message : str, translation : str|None = None):
        super().__init__(message=message, translation=translation)

class TranslationValidationError(TranslationError):
    def __init__(self, message : str, lines : list[Any]|None = None, translation : Any|None = None):
        super().__init__(message, translation)
        self.lines = lines or []

class UntranslatedLinesError(TranslationValidationError):
    def __init__(self, message : str, lines : list[Any]|None = None, translation : Any|None = None):
        super().__init__(message, lines=lines, translation=translation)

class UnmatchedLinesError(TranslationValidationError):
    def __init__(self, message : str, lines : list[Any]|None = None, translation : Any|None = None):
        super().__init__(message, lines=lines, translation=translation)

class EmptyLinesError(TranslationValidationError):
    def __init__(self, message : str, lines : list[Any]|None = None, translation : Any|None = None):
        super().__init__(message, lines=lines, translation=translation)

class TooManyNewlinesError(TranslationValidationError):
    def __init__(self, message : str, lines : list[Any]|None = None, translation : Any|None = None):
        super().__init__(message, lines=lines, translation=translation)

class LineTooLongError(TranslationValidationError):
    def __init__(self, message : str, lines : list[Any]|None = None, translation : Any|None = None):
        super().__init__(message, lines=lines, translation=translation)

class SubtitleParseError(SubtitleError):
    """Error raised when subtitle file cannot be parsed."""
    def __init__(self, message : str, error : Exception|None = None):
        super().__init__(message, error)
 
