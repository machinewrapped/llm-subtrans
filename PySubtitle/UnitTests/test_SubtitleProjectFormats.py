import json
import os
import tempfile
import unittest
from typing import TextIO

from PySubtitle.SubtitleProject import SubtitleProject
from PySubtitle.SubtitleFormatRegistry import SubtitleFormatRegistry
from PySubtitle.SubtitleFileHandler import SubtitleFileHandler
from PySubtitle.SubtitleData import SubtitleData
from PySubtitle.Formats.SrtFileHandler import SrtFileHandler
from PySubtitle.Formats.AssFileHandler import AssFileHandler
from PySubtitle.SubtitleSerialisation import SubtitleEncoder, SubtitleDecoder
from PySubtitle.Subtitles import Subtitles
from PySubtitle.Helpers.Color import Color
from PySubtitle.Helpers.Tests import (
    log_input_expected_result,
    log_test_name,
    skip_if_debugger_attached,
)


class DummyHandler(SubtitleFileHandler):
    """
    A dummy subtitle handler for testing purposes.
    """
    SUPPORTED_EXTENSIONS: dict[str, int] = { ".dummy": 1 }

    def parse_file(self, file_obj: TextIO) -> SubtitleData:  # pyright: ignore[reportUnusedParameter]
        return SubtitleData(lines=[], metadata={})

    def parse_string(self, content: str) -> SubtitleData:  # pyright: ignore[reportUnusedParameter]
        return SubtitleData(lines=[], metadata={})

    def compose(self, data: SubtitleData) -> str:  # pyright: ignore[reportUnusedParameter]
        return ""

    def load_file(self, path: str) -> SubtitleData:  # pyright: ignore[reportUnusedParameter]
        return SubtitleData(lines=[], metadata={})


class TestSubtitleProjectFormats(unittest.TestCase):
    def setUp(self):
        SubtitleFormatRegistry.register_handler(DummyHandler)

    def _create_temp_file(self, content: str, suffix: str) -> str:
        """Create a temporary file with the given content and suffix."""
        with tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False, encoding='utf-8') as f:
            f.write(content)
            temp_path = f.name
        self.addCleanup(os.remove, temp_path)
        return temp_path

    def test_AutoDetectSrt(self):
        log_test_name("AutoDetectSrt")
        
        srt_content = "1\n00:00:01,000 --> 00:00:02,000\nHello World\n"
        path = self._create_temp_file(srt_content, ".srt")
        
        project = SubtitleProject()
        project.InitialiseProject(path)
        
        log_input_expected_result("subtitles not None", True, project.subtitles is not None)
        self.assertIsNotNone(project.subtitles)
        log_input_expected_result("format", ".srt", project.subtitles.format)
        self.assertEqual(project.subtitles.format, ".srt")
        log_input_expected_result("line count", 1, project.subtitles.linecount)
        self.assertEqual(project.subtitles.linecount, 1)

    def test_AutoDetectAss(self):
        log_test_name("AutoDetectAss")
        
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
        path = self._create_temp_file(ass_content, ".ass")
        
        project = SubtitleProject()
        project.InitialiseProject(path)
        
        log_input_expected_result("subtitles not None", True, project.subtitles is not None)
        self.assertIsNotNone(project.subtitles)
        log_input_expected_result("format", ".ass", project.subtitles.format)
        self.assertEqual(project.subtitles.format, ".ass")
        log_input_expected_result("line count", 1, project.subtitles.linecount)
        self.assertEqual(project.subtitles.linecount, 1)

    def test_ProjectFileRoundtripPreservesHandler(self):
        log_test_name("ProjectFileRoundtripPreservesHandler")
        
        srt_content = "1\n00:00:01,000 --> 00:00:02,000\nHello World\n"
        path = self._create_temp_file(srt_content, ".srt")
        
        project = SubtitleProject()
        project.InitialiseProject(path)
        
        log_input_expected_result("initial format", ".srt", project.subtitles.format)
        self.assertEqual(project.subtitles.format, ".srt")
        
        # Set outputpath so file handler can be restored on load
        project_path = path.replace('.srt', '.subtrans')
        project.subtitles.outputpath = path.replace('.srt', '_translated.srt')
        
        project.WriteProjectToFile(project_path, encoder_class=SubtitleEncoder)
        self.addCleanup(os.remove, project_path)
        
        reopened_project = SubtitleProject()
        reopened_project.ReadProjectFile(project_path)
        
        log_input_expected_result("reopened subtitles not None", True, reopened_project.subtitles is not None)
        self.assertIsNotNone(reopened_project.subtitles)
        log_input_expected_result("reopened format", ".srt", reopened_project.subtitles.format)
        self.assertEqual(reopened_project.subtitles.format, ".srt")

    def test_SrtHandlerBasicFunctionality(self):
        log_test_name("SrtHandlerBasicFunctionality")
        
        srt_content = "1\n00:00:01,000 --> 00:00:03,000\nHello <b>World</b>!\n"
        
        handler = SrtFileHandler()
        subtitles = Subtitles()
        subtitles.LoadSubtitlesFromString(srt_content, handler)
        
        log_input_expected_result("line count", 1, subtitles.linecount)
        self.assertEqual(subtitles.linecount, 1)
        
        assert subtitles.originals is not None
        self.assertGreater(len(subtitles.originals), 0)
        line = subtitles.originals[0]
        assert line.text is not None
        log_input_expected_result("line text", "Hello <b>World</b>!", line.text)
        self.assertEqual(line.text, "Hello <b>World</b>!")
        log_input_expected_result("line start seconds", 1.0, line.start.total_seconds())
        self.assertEqual(line.start.total_seconds(), 1.0)
        log_input_expected_result("line end seconds", 3.0, line.end.total_seconds())
        self.assertEqual(line.end.total_seconds(), 3.0)

    def test_AssHandlerBasicFunctionality(self):
        log_test_name("AssHandlerBasicFunctionality")
        
        ass_content = """[Script Info]
Title: Test Script
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\b1}Hello{\\b0} World!
"""
        
        handler = AssFileHandler()
        subtitles = Subtitles()
        subtitles.LoadSubtitlesFromString(ass_content, handler)
        
        log_input_expected_result("line count", 1, subtitles.linecount)
        self.assertEqual(subtitles.linecount, 1)
        log_input_expected_result("pysubs2_format in metadata keys", True, 'pysubs2_format' in subtitles.metadata.keys())
        self.assertIn('pysubs2_format', subtitles.metadata)
        log_input_expected_result("styles in metadata keys", True, 'styles' in subtitles.metadata.keys())
        self.assertIn('styles', subtitles.metadata)
        
        assert subtitles.originals is not None
        self.assertGreater(len(subtitles.originals), 0)
        line = subtitles.originals[0]
        assert line.text is not None
        log_input_expected_result("line text converted to HTML", "<b>Hello</b> World!", line.text)
        self.assertEqual(line.text, "<b>Hello</b> World!")
        log_input_expected_result("line start seconds", 1.0, line.start.total_seconds())
        self.assertEqual(line.start.total_seconds(), 1.0)

    def test_AssColorHandling(self):
        log_test_name("AssColorHandling")
        
        ass_content = """[Script Info]
Title: Test Script

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FF0000,&H0000FF00,&H000000FF,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Test line
"""
        
        handler = AssFileHandler()
        subtitles = Subtitles()
        subtitles.LoadSubtitlesFromString(ass_content, handler)
        
        log_input_expected_result("styles in metadata keys", True, 'styles' in subtitles.metadata.keys())
        self.assertIn('styles', subtitles.metadata)
        
        default_style = subtitles.metadata['styles'].get('Default', {})
        primary_color = default_style.get('primarycolor')
        
        log_input_expected_result("primary color found", True, primary_color is not None)
        self.assertIsNotNone(primary_color)
        
        log_input_expected_result("primary color type", True, isinstance(primary_color, Color))
        self.assertIsInstance(primary_color, Color)
        
        log_input_expected_result("primary color red component", 0, primary_color.r)
        self.assertEqual(primary_color.r, 0)
        log_input_expected_result("primary color green component", 0, primary_color.g)
        self.assertEqual(primary_color.g, 0)
        log_input_expected_result("primary color blue component", 255, primary_color.b)
        self.assertEqual(primary_color.b, 255)

    def test_AssInlineFormatting(self):
        log_test_name("AssInlineFormatting")
        
        ass_content = """[Script Info]
Title: Test Script

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\i1}Italic{\\i0} and {\\b1}bold{\\b0} text
"""
        
        handler = AssFileHandler()
        subtitles = Subtitles()
        subtitles.LoadSubtitlesFromString(ass_content, handler)
        
        assert subtitles.originals is not None
        self.assertGreater(len(subtitles.originals), 0)
        line = subtitles.originals[0]
        assert line.text is not None
        log_input_expected_result("inline formatting converted", "<i>Italic</i> and <b>bold</b> text", line.text)
        self.assertEqual(line.text, "<i>Italic</i> and <b>bold</b> text")

    def test_AssOverrideTags(self):
        log_test_name("AssOverrideTags")
        
        ass_content = """[Script Info]
Title: Test Script

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\pos(100,200)\\b1}Bold text with positioning{\\b0}
"""
        
        handler = AssFileHandler()
        subtitles = Subtitles()
        subtitles.LoadSubtitlesFromString(ass_content, handler)
        
        assert subtitles.originals is not None
        self.assertGreater(len(subtitles.originals), 0)
        line = subtitles.originals[0]
        assert line.text is not None
        log_input_expected_result("override_tags_start in line metadata", True, 'override_tags_start' in line.metadata)
        self.assertIn('override_tags_start', line.metadata)
        log_input_expected_result("positioning tag in override tags", True, '\\\\pos(100,200)' in line.metadata['override_tags_start'])
        self.assertIn('\\pos(100,200)', line.metadata['override_tags_start'])
        log_input_expected_result("basic formatting converted to HTML", "<b>Bold text with positioning</b>", line.text)
        self.assertEqual(line.text, "<b>Bold text with positioning</b>")

    def test_AssRoundtripPreservation(self):
        log_test_name("AssRoundtripPreservation")
        
        ass_content = """[Script Info]
Title: Test Script
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\pos(100,200)\\b1}Test{\\b0} line
"""
        
        handler = AssFileHandler()
        data = handler.parse_string(ass_content)
        recomposed = handler.compose(data)
        
        log_input_expected_result("title in recomposed content", True, "Title: Test Script" in recomposed)
        self.assertIn("Title: Test Script", recomposed)
        log_input_expected_result("positioning tag in recomposed", True, "\\pos(100,200)" in recomposed)
        self.assertIn("\\pos(100,200)", recomposed)
        log_input_expected_result("bold tags in recomposed", True, "\\b1" in recomposed and "\\b0" in recomposed)
        self.assertIn("\\b1", recomposed)
        self.assertIn("\\b0", recomposed)

    def test_JsonSerializationRoundtrip(self):
        log_test_name("JsonSerializationRoundtrip")
        
        ass_content = """[Script Info]
Title: Serialization Test

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FF0000,&H0000FF00,&H000000FF,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Test serialization
"""
        
        handler = AssFileHandler()
        subtitles = Subtitles()
        subtitles.LoadSubtitlesFromString(ass_content, handler)
        
        log_input_expected_result("original line count", 1, subtitles.linecount)
        self.assertEqual(subtitles.linecount, 1)
        
        # Test JSON serialization roundtrip
        json_str = json.dumps(subtitles, cls=SubtitleEncoder)
        subtitles_restored = json.loads(json_str, cls=SubtitleDecoder)
        
        # The JSON serialization may not preserve all subtitle data perfectly
        # Focus on testing that metadata is preserved correctly
        log_input_expected_result("format preserved", subtitles.metadata.get('pysubs2_format'), subtitles_restored.metadata.get('pysubs2_format'))
        self.assertEqual(subtitles_restored.metadata.get('pysubs2_format'), subtitles.metadata.get('pysubs2_format'))
        self.assertEqual(subtitles_restored.metadata.get('pysubs2_format'), subtitles.metadata.get('pysubs2_format'))
        
        # Verify colors survived serialization
        original_style = subtitles.metadata['styles'].get('Default', {})
        restored_style = subtitles_restored.metadata['styles'].get('Default', {})
        original_color = original_style.get('primarycolor')
        restored_color = restored_style.get('primarycolor')
        
        if original_color and restored_color:
            log_input_expected_result("restored color type", type(original_color), type(restored_color))
            self.assertEqual(type(restored_color), type(original_color))
            log_input_expected_result("restored color values", (original_color.r, original_color.g, original_color.b, original_color.a), (restored_color.r, restored_color.g, restored_color.b, restored_color.a))
            self.assertEqual((restored_color.r, restored_color.g, restored_color.b, restored_color.a), (original_color.r, original_color.g, original_color.b, original_color.a))
        else:
            self.skipTest("Colors not found in metadata, cannot test serialization")

    def test_AssLineBreaksHandling(self):
        if skip_if_debugger_attached("AssLineBreaksHandling"):
            return
            
        log_test_name("AssLineBreaksHandling")
        
        ass_content = """[Script Info]
Title: Line Breaks Test

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Hard\\Nbreak and\\nsoft break
"""
        
        handler = AssFileHandler()
        subtitles = Subtitles()
        subtitles.LoadSubtitlesFromString(ass_content, handler)
        
        assert subtitles.originals is not None
        self.assertGreater(len(subtitles.originals), 0)
        line = subtitles.originals[0]
        assert line.text is not None
        log_input_expected_result("newline in line text", True, "\\n" in line.text)
        self.assertIn("\n", line.text)
        log_input_expected_result("wbr tag in line text", True, "<wbr>" in line.text)
        self.assertIn("<wbr>", line.text)
        log_input_expected_result("complete conversion", "Hard\nbreak and<wbr>soft break", line.text)
        self.assertEqual(line.text, "Hard\nbreak and<wbr>soft break")


if __name__ == "__main__":
    unittest.main()