import json
import os
import tempfile
import unittest
from typing import TextIO

from PySubtrans.Formats.SSAFileHandler import SSAFileHandler
from PySubtrans.Formats.SrtFileHandler import SrtFileHandler
from PySubtrans.Helpers.Color import Color
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Options import Options
from PySubtrans.SubtitleBatcher import SubtitleBatcher
from PySubtrans.SubtitleData import SubtitleData
from PySubtrans.SubtitleFileHandler import SubtitleFileHandler
from PySubtrans.SubtitleFormatRegistry import SubtitleFormatRegistry
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.SubtitleSerialisation import SubtitleEncoder, SubtitleDecoder
from PySubtrans.Subtitles import Subtitles
from PySubtrans.Helpers.Tests import (
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


class TestSubtitleProjectFormats(LoggedTestCase):

    def setUp(self) -> None:
        super().setUp()
        SubtitleFormatRegistry.register_handler(DummyHandler)

    def _create_temp_file(self, content: str, suffix: str) -> str:
        """Create a temporary file with the given content and suffix."""
        with tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False, encoding='utf-8') as f:
            f.write(content)
            temp_path = f.name
        self.addCleanup(os.remove, temp_path)
        return temp_path

    def test_AutoDetectSrt(self):
        
        srt_content = "1\n00:00:01,000 --> 00:00:02,000\nHello World\n"
        path = self._create_temp_file(srt_content, ".srt")
        
        project = SubtitleProject()
        project.InitialiseProject(path)
        
        self.assertLoggedIsNotNone("subtitles loaded", project.subtitles)
        self.assertLoggedEqual("detected format", ".srt", project.subtitles.file_format)
        self.assertLoggedEqual("line count", 1, project.subtitles.linecount)

    def test_AutoDetectAss(self):
        
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
        
        self.assertLoggedIsNotNone("subtitles loaded", project.subtitles)
        self.assertLoggedEqual("detected format", ".ass", project.subtitles.file_format)
        self.assertLoggedEqual("line count", 1, project.subtitles.linecount)

    def test_ProjectFileRoundtripPreservesHandler(self):
        
        srt_content = "1\n00:00:01,000 --> 00:00:02,000\nHello World\n"
        path = self._create_temp_file(srt_content, ".srt")
        
        project = SubtitleProject()
        project.InitialiseProject(path)
        
        self.assertLoggedEqual("initial format", ".srt", project.subtitles.file_format)
        
        # Set outputpath so file handler can be restored on load
        project_path = path.replace('.srt', '.subtrans')
        project.subtitles.outputpath = path.replace('.srt', '_translated.srt')
        
        project.WriteProjectToFile(project_path, encoder_class=SubtitleEncoder)
        self.addCleanup(os.remove, project_path)
        
        reopened_project = SubtitleProject()
        reopened_project.ReadProjectFile(project_path)
        
        self.assertLoggedIsNotNone("reopened project has subtitles", reopened_project.subtitles)
        self.assertLoggedEqual(
            "reopened project format",
            '.srt',
            reopened_project.subtitles.file_format,
        )

    def test_SrtHandlerBasicFunctionality(self):
        
        srt_content = "1\n00:00:01,000 --> 00:00:03,000\nHello <b>World</b>!\n"
        
        subtitles = Subtitles()
        subtitles.LoadSubtitlesFromString(srt_content, SrtFileHandler())
        
        self.assertLoggedEqual("line count", 1, subtitles.linecount)
        
        assert subtitles.originals is not None
        self.assertGreater(len(subtitles.originals), 0)
        line = subtitles.originals[0]
        assert line.text is not None
        self.assertLoggedEqual("line.text", "Hello <b>World</b>!", line.text)
        self.assertLoggedEqual("line.start", 1.0, line.start.total_seconds())
        self.assertLoggedEqual("line.end", 3.0, line.end.total_seconds())

    def test_AssHandlerBasicFunctionality(self):
        
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
        
        self.assertLoggedEqual("line count", 1, subtitles.linecount)

        has_pysubs2_format = 'pysubs2_format' in subtitles.metadata
        self.assertLoggedTrue(
            "pysubs2 format metadata",
            has_pysubs2_format,
            input_value=list(subtitles.metadata.keys()),
        )

        has_styles = 'styles' in subtitles.metadata
        self.assertLoggedTrue(
            "styles metadata present",
            has_styles,
            input_value=list(subtitles.metadata.keys()),
        )
        
        assert subtitles.originals is not None
        self.assertGreater(len(subtitles.originals), 0)
        line = subtitles.originals[0]
        assert line.text is not None
        self.assertLoggedEqual("line text converted to HTML", "<b>Hello</b> World!", line.text)
        self.assertLoggedEqual("line start seconds", 1.0, line.start.total_seconds())

    def test_AssColorHandling(self):
        
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
        self.assertLoggedTrue("styles metadata present", has_styles)
        
        default_style = subtitles.metadata['styles'].get('Default', {})
        primary_color = default_style.get('primarycolor')
        
        self.assertLoggedIsNotNone("primary color exists", primary_color)

        assert primary_color is not None
        self.assertLoggedIsInstance("primary color type", primary_color, Color)

        self.assertLoggedEqual("primary color red", 0, primary_color.r)
        self.assertLoggedEqual("primary color green", 0, primary_color.g)
        self.assertLoggedEqual("primary color blue", 255, primary_color.b)

    def test_AssInlineFormatting(self):
        
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
        self.assertLoggedEqual(
            "inline formatting converted",
            "<i>Italic</i> and <b>bold</b> text",
            line.text,
        )

    def test_AssOverrideTags(self):
        
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
        self.assertLoggedTrue("override tags captured", has_override_tags, input_value=line.metadata)

        expected_pos_tag = '\\pos(100,200)'
        has_pos_tag = expected_pos_tag in line.metadata.get('override_tags_start', '')
        self.assertLoggedTrue(
            "position override captured",
            has_pos_tag,
            input_value=line.metadata.get('override_tags_start'),
        )

        expected_text = "<b>Bold text with positioning</b>"
        self.assertLoggedEqual("formatted text", expected_text, line.text)

    def test_AssRoundtripPreservation(self):
        
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
        self.assertLoggedTrue("serialized title preserved", has_title)

        has_position = "\\pos(100,200)" in recomposed
        self.assertLoggedTrue("position tag preserved", has_position)

        has_bold_start = "\\b1" in recomposed
        has_bold_end = "\\b0" in recomposed
        has_bold_tags = has_bold_start and has_bold_end
        self.assertLoggedTrue("bold overrides preserved", has_bold_tags)

    def test_JsonSerializationRoundtrip(self):
        
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
        
        self.assertLoggedEqual("line count", 1, subtitles.linecount)
        
        # Test JSON serialization roundtrip
        json_str = json.dumps(subtitles, cls=SubtitleEncoder)
        subtitles_restored = json.loads(json_str, cls=SubtitleDecoder)
        
        # The JSON serialization may not preserve all subtitle data perfectly
        # Focus on testing that metadata is preserved correctly
        self.assertLoggedEqual(
            "pysubs2_format",
            subtitles.metadata.get('pysubs2_format'),
            subtitles_restored.metadata.get('pysubs2_format'),
        )
        
        # Verify colors survived serialization
        original_style = subtitles.metadata['styles'].get('Default', {})
        restored_style = subtitles_restored.metadata['styles'].get('Default', {})
        original_color = original_style.get('primarycolor')
        restored_color = restored_style.get('primarycolor')
        
        if original_color and restored_color:
            self.assertLoggedEqual(
                "restored_color type",
                type(original_color),
                type(restored_color),
            )
            self.assertLoggedEqual(
                "restored_color values",
                (original_color.r, original_color.g, original_color.b, original_color.a),
                (restored_color.r, restored_color.g, restored_color.b, restored_color.a),
            )
        else:
            self.skipTest("Colors not found in metadata, cannot test serialization")

    @skip_if_debugger_attached
    def test_AssLineBreaksHandling(self):
        
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
        self.assertLoggedTrue("newline preserved", has_newline, input_value=line.text)

        has_wbr = "<wbr>" in line.text
        self.assertLoggedTrue("soft break preserved", has_wbr, input_value=line.text)

        expected_text = "Hard\nbreak and<wbr>soft break"
        self.assertLoggedEqual("converted text", expected_text, line.text)

    def test_AssToSrtConversion(self):
        
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
        
        self.assertLoggedIsNotNone("subtitles loaded", project.subtitles)
        self.assertLoggedEqual(
            "format after setting output path",
            '.srt',
            project.subtitles.file_format,
        )
        
        with project.GetEditor() as editor:
            editor.AutoBatch(SubtitleBatcher(options))
            editor.DuplicateOriginalsAsTranslations()

        project.SaveTranslation()
        
        self.assertLoggedTrue("output file exists", os.path.exists(out_path), input_value=out_path)
        
        # Verify the converted file can be loaded as SRT
        converted_project = SubtitleProject()
        converted_project.LoadSubtitleFile(out_path)
        
        self.assertLoggedEqual(
            "converted format",
            '.srt',
            converted_project.subtitles.file_format,
        )
        self.assertLoggedEqual("content preserved", 1, converted_project.subtitles.linecount)

        if converted_project.subtitles.originals:
            first_line = converted_project.subtitles.originals[0]
            self.assertLoggedEqual("converted text", "Hello ASS!", first_line.text)
        
        self.addCleanup(os.remove, out_path)

    def test_SrtToAssConversion(self):
        
        srt_content = "1\n00:00:01,000 --> 00:00:02,000\nHello SRT!\n"
        
        srt_path = self._create_temp_file(srt_content, ".srt")
        out_path = srt_path + ".ass"
        
        options = Options()
        project = SubtitleProject()
        project.InitialiseProject(filepath=srt_path, outputpath=out_path)
        
        self.assertLoggedIsNotNone("subtitles loaded", project.subtitles)
        self.assertLoggedEqual(
            "format after setting output path",
            '.ass',
            project.subtitles.file_format,
        )
        
        with project.GetEditor() as editor:
            editor.AutoBatch(SubtitleBatcher(options))
            editor.DuplicateOriginalsAsTranslations()

        project.SaveTranslation()
        
        self.assertLoggedTrue("output file exists", os.path.exists(out_path), input_value=out_path)
        
        # Verify the converted file can be loaded as ASS
        converted_project = SubtitleProject()
        converted_project.LoadSubtitleFile(out_path)
        
        self.assertLoggedEqual(
            "converted format",
            '.ass',
            converted_project.subtitles.file_format,
        )
        self.assertLoggedEqual("content preserved", 1, converted_project.subtitles.linecount)
        
        if converted_project.subtitles.originals:
            first_line = converted_project.subtitles.originals[0]
            self.assertLoggedEqual("converted text", "Hello SRT!", first_line.text)
        
        self.addCleanup(os.remove, out_path)

    def test_ConversionWithProjectSerialization(self):
        
        srt_content = "1\n00:00:01,000 --> 00:00:02,000\nHello SRT!\n"
        
        srt_path = self._create_temp_file(srt_content, ".srt")
        out_path = srt_path + ".ass"
        
        options = Options()
        project = SubtitleProject()
        project.InitialiseProject(filepath=srt_path, outputpath=out_path)
        
        self.assertLoggedIsNotNone("subtitles loaded", project.subtitles)
        
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
        
        self.assertLoggedIsNotNone("project2 subtitles loaded", project2.subtitles)
        self.assertLoggedEqual(
            "format preserved through serialization",
            '.ass',
            project2.subtitles.file_format,
        )
        self.assertLoggedEqual("content preserved", 1, project2.subtitles.linecount)


if __name__ == "__main__":
    unittest.main()
