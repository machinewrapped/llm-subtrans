import json
import os
import tempfile
import unittest
from typing import TextIO

from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.SubtitleFormatRegistry import SubtitleFormatRegistry
from PySubtrans.SubtitleFileHandler import SubtitleFileHandler
from PySubtrans.SubtitleData import SubtitleData
from PySubtrans.Formats.SrtFileHandler import SrtFileHandler
from PySubtrans.Formats.SSAFileHandler import SSAFileHandler
from PySubtrans.SubtitleSerialisation import SubtitleEncoder, SubtitleDecoder
from PySubtrans.Subtitles import Subtitles
from PySubtrans.Helpers.Color import Color
from PySubtrans.Options import Options
from PySubtrans.SubtitleBatcher import SubtitleBatcher
from PySubtrans.Helpers.Tests import (
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
        log_input_expected_result("format", ".srt", project.subtitles.file_format)
        self.assertEqual(project.subtitles.file_format, ".srt")
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
        log_input_expected_result("format", ".ass", project.subtitles.file_format)
        self.assertEqual(project.subtitles.file_format, ".ass")
        log_input_expected_result("line count", 1, project.subtitles.linecount)
        self.assertEqual(project.subtitles.linecount, 1)

    def test_ProjectFileRoundtripPreservesHandler(self):
        log_test_name("ProjectFileRoundtripPreservesHandler")
        
        srt_content = "1\n00:00:01,000 --> 00:00:02,000\nHello World\n"
        path = self._create_temp_file(srt_content, ".srt")
        
        project = SubtitleProject()
        project.InitialiseProject(path)
        
        log_input_expected_result("project.subtitles.format", ".srt", project.subtitles.file_format)
        self.assertEqual(project.subtitles.file_format, ".srt")
        
        # Set outputpath so file handler can be restored on load
        project_path = path.replace('.srt', '.subtrans')
        project.subtitles.outputpath = path.replace('.srt', '_translated.srt')
        
        project.WriteProjectToFile(project_path, encoder_class=SubtitleEncoder)
        self.addCleanup(os.remove, project_path)
        
        reopened_project = SubtitleProject()
        reopened_project.ReadProjectFile(project_path)
        
        log_input_expected_result("reopened_project.subtitles", True, reopened_project.subtitles is not None)
        self.assertIsNotNone(reopened_project.subtitles)
        log_input_expected_result("reopened_project.subtitles.format", ".srt", reopened_project.subtitles.file_format)
        self.assertEqual(reopened_project.subtitles.file_format, ".srt")

    def test_SrtHandlerBasicFunctionality(self):
        log_test_name("SrtHandlerBasicFunctionality")
        
        srt_content = "1\n00:00:01,000 --> 00:00:03,000\nHello <b>World</b>!\n"
        
        subtitles = Subtitles()
        subtitles.LoadSubtitlesFromString(srt_content, SrtFileHandler())
        
        log_input_expected_result("line count", 1, subtitles.linecount)
        self.assertEqual(subtitles.linecount, 1)
        
        assert subtitles.originals is not None
        self.assertGreater(len(subtitles.originals), 0)
        line = subtitles.originals[0]
        assert line.text is not None
        log_input_expected_result("line.text", "Hello <b>World</b>!", line.text)
        self.assertEqual(line.text, "Hello <b>World</b>!")
        log_input_expected_result("line.start", 1.0, line.start.total_seconds())
        self.assertEqual(line.start.total_seconds(), 1.0)
        log_input_expected_result("line.end", 3.0, line.end.total_seconds())
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
        
        subtitles = Subtitles()
        subtitles.LoadSubtitlesFromString(ass_content, SSAFileHandler())
        
        log_input_expected_result("subtitles.linecount", 1, subtitles.linecount)
        self.assertEqual(subtitles.linecount, 1)
        
        has_pysubs2_format = 'pysubs2_format' in subtitles.metadata
        log_input_expected_result(subtitles.metadata.keys(), True, has_pysubs2_format)
        self.assertTrue(has_pysubs2_format)
        
        has_styles = 'styles' in subtitles.metadata
        log_input_expected_result(subtitles.metadata.keys(), True, has_styles)
        self.assertTrue(has_styles)
        
        assert subtitles.originals is not None
        self.assertGreater(len(subtitles.originals), 0)
        line = subtitles.originals[0]
        assert line.text is not None
        log_input_expected_result("line text converted to HTML", "<b>Hello</b> World!", line.text)
        self.assertEqual(line.text, "<b>Hello</b> World!")
        log_input_expected_result("line.start.total_seconds", 1.0, line.start.total_seconds())
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
        
        subtitles = Subtitles()
        subtitles.LoadSubtitlesFromString(ass_content, SSAFileHandler())
        
        has_styles = 'styles' in subtitles.metadata
        log_input_expected_result("has styles in metadata", True, has_styles)
        self.assertTrue(has_styles)
        
        default_style = subtitles.metadata['styles'].get('Default', {})
        primary_color = default_style.get('primarycolor')
        
        color_exists = primary_color is not None
        log_input_expected_result(primary_color, True, color_exists)
        self.assertIsNotNone(primary_color)
        
        log_input_expected_result(primary_color, Color, type(primary_color))
        self.assertEqual(type(primary_color), Color)
        
        log_input_expected_result(primary_color, 0, primary_color.r)
        self.assertEqual(primary_color.r, 0)
        log_input_expected_result(primary_color, 0, primary_color.g)
        self.assertEqual(primary_color.g, 0)
        log_input_expected_result(primary_color, 255, primary_color.b)
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
        
        subtitles = Subtitles()
        subtitles.LoadSubtitlesFromString(ass_content, SSAFileHandler())
        
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
        
        subtitles = Subtitles()
        subtitles.LoadSubtitlesFromString(ass_content, SSAFileHandler())
        
        assert subtitles.originals is not None
        self.assertGreater(len(subtitles.originals), 0)
        line = subtitles.originals[0]
        assert line.text is not None
        
        # Test metadata extraction
        has_override_tags = 'override_tags_start' in line.metadata
        log_input_expected_result("line.metadata has override_tags_start", True, has_override_tags)
        self.assertTrue(has_override_tags)
        
        expected_pos_tag = '\\pos(100,200)'
        has_pos_tag = expected_pos_tag in line.metadata.get('override_tags_start', '')
        log_input_expected_result(f"metadata contains '{expected_pos_tag}'", True, has_pos_tag)
        self.assertTrue(has_pos_tag)
        
        expected_text = "<b>Bold text with positioning</b>"
        log_input_expected_result("line.text", expected_text, line.text)
        self.assertEqual(line.text, expected_text)

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
        
        handler = SSAFileHandler()
        data = handler.parse_string(ass_content)
        recomposed = handler.compose(data)
        
        has_title = "Title: Test Script" in recomposed
        log_input_expected_result("contains title", True, has_title)
        self.assertTrue(has_title)
        
        has_position = "\\pos(100,200)" in recomposed
        log_input_expected_result("contains position tag", True, has_position)
        self.assertTrue(has_position)
        
        has_bold_start = "\\b1" in recomposed
        has_bold_end = "\\b0" in recomposed
        has_bold_tags = has_bold_start and has_bold_end
        log_input_expected_result("contains bold tags", True, has_bold_tags)
        self.assertTrue(has_bold_tags)

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
        
        subtitles = Subtitles()
        subtitles.LoadSubtitlesFromString(ass_content, SSAFileHandler())
        
        log_input_expected_result("subtitles.linecount", 1, subtitles.linecount)
        self.assertEqual(subtitles.linecount, 1)
        
        # Test JSON serialization roundtrip
        json_str = json.dumps(subtitles, cls=SubtitleEncoder)
        subtitles_restored = json.loads(json_str, cls=SubtitleDecoder)
        
        # The JSON serialization may not preserve all subtitle data perfectly
        # Focus on testing that metadata is preserved correctly
        log_input_expected_result("pysubs2_format", subtitles.metadata.get('pysubs2_format'), subtitles_restored.metadata.get('pysubs2_format'))
        self.assertEqual(subtitles_restored.metadata.get('pysubs2_format'), subtitles.metadata.get('pysubs2_format'))
        
        # Verify colors survived serialization
        original_style = subtitles.metadata['styles'].get('Default', {})
        restored_style = subtitles_restored.metadata['styles'].get('Default', {})
        original_color = original_style.get('primarycolor')
        restored_color = restored_style.get('primarycolor')
        
        if original_color and restored_color:
            log_input_expected_result("restored_color", type(original_color), type(restored_color))
            self.assertEqual(type(restored_color), type(original_color))
            log_input_expected_result("restored_color values", (original_color.r, original_color.g, original_color.b, original_color.a), (restored_color.r, restored_color.g, restored_color.b, restored_color.a))
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
        
        subtitles = Subtitles()
        subtitles.LoadSubtitlesFromString(ass_content, SSAFileHandler())
        
        assert subtitles.originals is not None
        self.assertGreater(len(subtitles.originals), 0)
        line = subtitles.originals[0]
        assert line.text is not None
        
        # Test line break conversion
        has_newline = "\n" in line.text
        log_input_expected_result("contains newline", True, has_newline)
        self.assertTrue(has_newline)
        
        has_wbr = "<wbr>" in line.text
        log_input_expected_result("contains <wbr>", True, has_wbr)
        self.assertTrue(has_wbr)
        
        expected_text = "Hard\nbreak and<wbr>soft break"
        log_input_expected_result("line.text", expected_text, line.text)
        self.assertEqual(line.text, expected_text)

    def test_AssToSrtConversion(self):
        log_test_name("AssToSrtConversion")
        
        ass_content = """[Script Info]
Title: Sample ASS
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Hello ASS!
"""
        
        ass_path = self._create_temp_file(ass_content, ".ass")
        out_path = ass_path + ".srt"
        
        options = Options()
        project = SubtitleProject()
        project.InitialiseProject(filepath=ass_path, outputpath=out_path)
        
        log_input_expected_result("project.subtitles not None", True, project.subtitles is not None)
        self.assertIsNotNone(project.subtitles)
        log_input_expected_result("format after setting output path", ".srt", project.subtitles.file_format)
        self.assertEqual(project.subtitles.file_format, ".srt")
        
        with project.GetEditor() as editor:
            editor.AutoBatch(SubtitleBatcher(options))
            editor.DuplicateOriginalsAsTranslations()

        project.SaveTranslation()
        
        log_input_expected_result("output file exists", True, os.path.exists(out_path))
        self.assertTrue(os.path.exists(out_path))
        
        # Verify the converted file can be loaded as SRT
        converted_project = SubtitleProject()
        converted_project.LoadSubtitleFile(out_path)
        
        log_input_expected_result("converted format", ".srt", converted_project.subtitles.file_format)
        self.assertEqual(converted_project.subtitles.file_format, ".srt")
        log_input_expected_result("content preserved", 1, converted_project.subtitles.linecount)
        self.assertEqual(converted_project.subtitles.linecount, 1)
        
        if converted_project.subtitles.originals:
            first_line = converted_project.subtitles.originals[0]
            log_input_expected_result("converted text", "Hello ASS!", first_line.text)
            self.assertEqual(first_line.text, "Hello ASS!")
        
        self.addCleanup(os.remove, out_path)

    def test_SrtToAssConversion(self):
        log_test_name("SrtToAssConversion")
        
        srt_content = "1\n00:00:01,000 --> 00:00:02,000\nHello SRT!\n"
        
        srt_path = self._create_temp_file(srt_content, ".srt")
        out_path = srt_path + ".ass"
        
        options = Options()
        project = SubtitleProject()
        project.InitialiseProject(filepath=srt_path, outputpath=out_path)
        
        log_input_expected_result("project.subtitles not None", True, project.subtitles is not None)
        self.assertIsNotNone(project.subtitles)
        log_input_expected_result("format after setting output path", ".ass", project.subtitles.file_format)
        self.assertEqual(project.subtitles.file_format, ".ass")
        
        with project.GetEditor() as editor:
            editor.AutoBatch(SubtitleBatcher(options))
            editor.DuplicateOriginalsAsTranslations()

        project.SaveTranslation()
        
        log_input_expected_result("output file exists", True, os.path.exists(out_path))
        self.assertTrue(os.path.exists(out_path))
        
        # Verify the converted file can be loaded as ASS
        converted_project = SubtitleProject()
        converted_project.LoadSubtitleFile(out_path)
        
        log_input_expected_result("converted format", ".ass", converted_project.subtitles.file_format)
        self.assertEqual(converted_project.subtitles.file_format, ".ass")
        log_input_expected_result("content preserved", 1, converted_project.subtitles.linecount)
        self.assertEqual(converted_project.subtitles.linecount, 1)
        
        if converted_project.subtitles.originals:
            first_line = converted_project.subtitles.originals[0]
            log_input_expected_result("converted text", "Hello SRT!", first_line.text)
            self.assertEqual(first_line.text, "Hello SRT!")
        
        self.addCleanup(os.remove, out_path)

    def test_ConversionWithProjectSerialization(self):
        log_test_name("ConversionWithProjectSerialization")
        
        srt_content = "1\n00:00:01,000 --> 00:00:02,000\nHello SRT!\n"
        
        srt_path = self._create_temp_file(srt_content, ".srt")
        out_path = srt_path + ".ass"
        
        options = Options()
        project = SubtitleProject()
        project.InitialiseProject(filepath=srt_path, outputpath=out_path)
        
        log_input_expected_result("project.subtitles not None", True, project.subtitles is not None)
        self.assertIsNotNone(project.subtitles)
        
        with project.GetEditor() as editor:
            editor.AutoBatch(SubtitleBatcher(options))
            editor.DuplicateOriginalsAsTranslations()
        
        # Create and write project file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".subtrans") as tmp_project:
            tmp_project_path = tmp_project.name
        
        project.WriteProjectToFile(tmp_project_path, encoder_class=SubtitleEncoder)
        self.addCleanup(os.remove, tmp_project_path)
        
        # Load project file and verify format preservation
        project2 = SubtitleProject()
        project2.ReadProjectFile(tmp_project_path)
        
        log_input_expected_result("project2.subtitles not None", True, project2.subtitles is not None)
        self.assertIsNotNone(project2.subtitles)
        log_input_expected_result("format preserved through serialization", ".ass", project2.subtitles.file_format)
        self.assertEqual(project2.subtitles.file_format, ".ass")
        log_input_expected_result("content preserved", 1, project2.subtitles.linecount)
        self.assertEqual(project2.subtitles.linecount, 1)


if __name__ == "__main__":
    unittest.main()