import tempfile
import unittest

from PySubtitle.Options import Options
from PySubtitle.SubtitleProject import SubtitleProject
from PySubtitle.SubtitleFormatRegistry import SubtitleFormatRegistry
from PySubtitle.SubtitleFileHandler import SubtitleFileHandler
from PySubtitle.SubtitleLine import SubtitleLine
from PySubtitle.Formats.SrtFileHandler import SrtFileHandler
from PySubtitle.Formats.VoidFileHandler import VoidFileHandler
from PySubtitle.SubtitleSerialisation import SubtitleEncoder
from typing import Iterator, TextIO


class DummyHandler(SubtitleFileHandler):
    def parse_file(self, file_obj: TextIO) -> Iterator[SubtitleLine]:
        return iter([])

    def parse_string(self, content: str) -> Iterator[SubtitleLine]:
        return iter([])

    def compose_lines(self, lines: list[SubtitleLine], reindex: bool = True) -> str:
        return ""

    def get_file_extensions(self) -> list[str]:
        return [".dummy"]


class TestSubtitleProjectFormats(unittest.TestCase):
    def setUp(self):
        SubtitleFormatRegistry.register_handler(DummyHandler)

    def _create_temp_srt(self) -> str:
        content = "1\n00:00:01,000 --> 00:00:02,000\nHello\n"
        f = tempfile.NamedTemporaryFile(delete=False, suffix=".srt")
        f.write(content.encode("utf-8"))
        f.flush()
        f.close()
        return f.name

    def test_auto_detect_srt(self):
        path = self._create_temp_srt()
        project = SubtitleProject(Options())
        self.assertIsInstance(project.subtitles.file_handler, VoidFileHandler)
        project.InitialiseProject(path)
        self.assertIsInstance(project.subtitles.file_handler, SrtFileHandler)

    def test_project_file_roundtrip_preserves_handler(self):
        path = self._create_temp_srt()
        project = SubtitleProject(Options())
        project.InitialiseProject(path)
        self.assertIsInstance(project.subtitles.file_handler, SrtFileHandler)

        tmp_project = tempfile.NamedTemporaryFile(delete=False, suffix=".subtrans")
        tmp_project.close()
        project.WriteProjectToFile(tmp_project.name, encoder_class=SubtitleEncoder)

        project2 = SubtitleProject(Options())
        project2.ReadProjectFile(tmp_project.name)
        self.assertIsInstance(project2.subtitles.file_handler, SrtFileHandler)


if __name__ == "__main__":
    unittest.main()

