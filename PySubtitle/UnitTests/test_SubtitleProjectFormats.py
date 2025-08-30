import tempfile
import unittest
import json

from PySubtitle.Options import Options
from PySubtitle.SubtitleProject import SubtitleProject
from PySubtitle.SubtitleFormatRegistry import SubtitleFormatRegistry
from PySubtitle.SubtitleFileHandler import SubtitleFileHandler
from PySubtitle.SubtitleData import SubtitleData
from PySubtitle.Formats.SrtFileHandler import SrtFileHandler
from PySubtitle.Formats.AssFileHandler import AssFileHandler
from PySubtitle.Formats.VoidFileHandler import VoidFileHandler
from PySubtitle.SubtitleSerialisation import SubtitleEncoder, SubtitleDecoder
from PySubtitle.Subtitles import Subtitles
from typing import TextIO


class DummyHandler(SubtitleFileHandler):
    def parse_file(self, file_obj: TextIO) -> SubtitleData:
        return SubtitleData(lines=[], metadata={})

    def parse_string(self, content: str) -> SubtitleData:
        return SubtitleData(lines=[], metadata={})

    def compose(self, data: SubtitleData) -> str:
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
        
        # Set outputpath so file handler can be restored on load
        project.subtitles.outputpath = path.replace('.srt', '_translated.srt')

        tmp_project = tempfile.NamedTemporaryFile(delete=False, suffix=".subtrans")
        tmp_project.close()
        project.WriteProjectToFile(tmp_project.name, encoder_class=SubtitleEncoder)

        project2 = SubtitleProject(Options())
        project2.ReadProjectFile(tmp_project.name)
        self.assertIsInstance(project2.subtitles.file_handler, SrtFileHandler)

    def test_srt_metadata_serialization(self):
        """Test SRT metadata survives JSON serialization through Subtitles."""
        srt_content = "1\n00:00:01,000 --> 00:00:03,000\nHello World!\n"
        
        # Create Subtitles with SRT handler and load content
        handler = SrtFileHandler()
        subtitles = Subtitles(handler)
        subtitles.LoadSubtitlesFromString(srt_content)
        
        # Verify basic loading
        self.assertEqual(subtitles.linecount, 1)
        self.assertEqual(subtitles.metadata.get('format'), 'srt')
        
        # Test JSON serialization roundtrip
        json_str = json.dumps(subtitles, cls=SubtitleEncoder)
        subtitles_restored = json.loads(json_str, cls=SubtitleDecoder)
        
        # Verify metadata survived (linecount will be 0 since VoidFileHandler is used on restore)
        self.assertEqual(subtitles_restored.metadata.get('format'), 'srt')
        # Note: linecount is 0 because deserialization creates VoidFileHandler by design

    def test_ass_metadata_serialization(self):
        """Test ASS metadata with colors survives JSON serialization through Subtitles."""
        ass_content = """[Script Info]
Title: Test Script
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Hello World!
"""
        
        # Create Subtitles with ASS handler and load content
        handler = AssFileHandler()
        subtitles = Subtitles(handler)
        subtitles.LoadSubtitlesFromString(ass_content)
        
        # Verify basic loading
        self.assertEqual(subtitles.linecount, 1)
        self.assertEqual(subtitles.metadata.get('format'), 'ass')
        self.assertIn('styles', subtitles.metadata)
        
        # Check that colors are properly converted to Color object
        default_style = subtitles.metadata['styles'].get('Default', {})
        primarycolor = default_style.get('primarycolor')
        from PySubtitle.Helpers.Color import Color
        self.assertIsInstance(primarycolor, Color)
        self.assertEqual(primarycolor.r, 255)
        self.assertEqual(primarycolor.g, 255)
        self.assertEqual(primarycolor.b, 255)
        self.assertEqual(primarycolor.a, 0)
        
        # Test JSON serialization roundtrip
        json_str = json.dumps(subtitles, cls=SubtitleEncoder)
        subtitles_restored = json.loads(json_str, cls=SubtitleDecoder)
        
        # Verify metadata survived (linecount will be 0 since VoidFileHandler is used on restore)
        self.assertEqual(subtitles_restored.metadata.get('format'), 'ass')
        self.assertIn('styles', subtitles_restored.metadata)
        
        # Verify colors survived serialization
        restored_default_style = subtitles_restored.metadata['styles'].get('Default', {})
        restored_primarycolor = restored_default_style.get('primarycolor')
        from PySubtitle.Helpers.Color import Color
        self.assertIsInstance(restored_primarycolor, Color)
        self.assertEqual(restored_primarycolor.r, 255)
        self.assertEqual(restored_primarycolor.g, 255)
        self.assertEqual(restored_primarycolor.b, 255)
        self.assertEqual(restored_primarycolor.a, 0)


if __name__ == "__main__":
    unittest.main()

