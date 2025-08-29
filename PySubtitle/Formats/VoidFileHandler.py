from typing import Iterator, TextIO

from PySubtitle.SubtitleFileHandler import SubtitleFileHandler
from PySubtitle.SubtitleLine import SubtitleLine


class VoidFileHandler(SubtitleFileHandler):
    """Placeholder handler used before a real format is determined."""

    def parse_file(self, file_obj: TextIO) -> Iterator[SubtitleLine]:
        raise NotImplementedError("VoidFileHandler cannot parse files")

    def parse_string(self, content: str) -> Iterator[SubtitleLine]:
        raise NotImplementedError("VoidFileHandler cannot parse strings")

    def compose_lines(self, lines: list[SubtitleLine], reindex: bool = True) -> str:
        raise NotImplementedError("VoidFileHandler cannot compose lines")

    def get_file_extensions(self) -> list[str]:
        return []
