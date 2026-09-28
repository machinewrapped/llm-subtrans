from typing import Any

from PySubtrans.SubtitleError import SubtitleError

class ViewModelError(SubtitleError):
    def __init__(self, message: str, error: Any = None):
        super().__init__(message, error)