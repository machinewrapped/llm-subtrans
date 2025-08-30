from typing import TextIO

from PySubtitle.SubtitleFileHandler import SubtitleFileHandler
from PySubtitle.SubtitleData import SubtitleData


class VoidFileHandler(SubtitleFileHandler):
    """Placeholder handler used before a real format is determined."""

    def parse_file(self, file_obj: TextIO) -> SubtitleData:
        raise NotImplementedError("VoidFileHandler cannot parse files")

    def parse_string(self, content: str) -> SubtitleData:
        raise NotImplementedError("VoidFileHandler cannot parse strings")

    def compose(self, data: SubtitleData) -> str:
        raise NotImplementedError("VoidFileHandler cannot compose data")

    def get_file_extensions(self) -> list[str]:
        return []
