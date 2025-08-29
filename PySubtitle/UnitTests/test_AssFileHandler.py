import unittest
from io import StringIO
from datetime import timedelta

from PySubtitle.Formats.AssFileHandler import AssFileHandler
from PySubtitle.SubtitleLine import SubtitleLine
from PySubtitle.SubtitleError import SubtitleParseError
from PySubtitle.Helpers.Tests import log_info, log_input_expected_result, log_test_name
from PySubtitle.Helpers.Time import AssTimeToTimedelta, TimedeltaToAssTime

class TestAssFileHandler(unittest.TestCase):
    """Test cases for ASS file handler."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.handler = AssFileHandler()
        
        # Sample ASS content for testing
        self.sample_ass_content = """[Script Info]
Title: Test Subtitles
ScriptType: v4.00+
PlayDepth: 0
ScaledBorderAndShadow: Yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,50,&H00FFFFFF,&H0000FFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,30,30,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.50,0:00:03.00,Default,,0,0,0,,First subtitle line
Dialogue: 0,0:00:04.00,0:00:06.50,Default,,0,0,0,,Second subtitle line\\Nwith line break
Dialogue: 0,0:00:07.00,0:00:09.00,Default,,0,0,0,,Third subtitle line
"""
        
        # Expected parsed lines
        self.expected_lines = [
            SubtitleLine.Construct(
                number=1,
                start=timedelta(seconds=1, milliseconds=500),
                end=timedelta(seconds=3),
                text="First subtitle line",
                metadata={
                    'format': 'ass',
                    'layer': 0,
                    'style': 'Default',
                    'name': '',
                    'margin_l': 0,
                    'margin_r': 0,
                    'margin_v': 0,
                    'effect': ''
                }
            ),
            SubtitleLine.Construct(
                number=2,
                start=timedelta(seconds=4),
                end=timedelta(seconds=6, milliseconds=500),
                text="Second subtitle line\nwith line break",
                metadata={
                    'format': 'ass',
                    'layer': 0,
                    'style': 'Default',
                    'name': '',
                    'margin_l': 0,
                    'margin_r': 0,
                    'margin_v': 0,
                    'effect': ''
                }
            ),
            SubtitleLine.Construct(
                number=3,
                start=timedelta(seconds=7),
                end=timedelta(seconds=9),
                text="Third subtitle line",
                metadata={
                    'format': 'ass',
                    'layer': 0,
                    'style': 'Default',
                    'name': '',
                    'margin_l': 0,
                    'margin_r': 0,
                    'margin_v': 0,
                    'effect': ''
                }
            )
        ]
    
    def test_get_file_extensions(self):
        """Test that the handler returns correct file extensions."""
        log_test_name("AssFileHandler.get_file_extensions")
        
        expected = ['.ass', '.ssa']
        result = self.handler.get_file_extensions()
        
        log_input_expected_result("", expected, result)
        self.assertEqual(result, expected)
    
    def test_parse_string_basic(self):
        """Test parsing of basic ASS content."""
        log_test_name("AssFileHandler.parse_string - basic parsing")
        
        lines = list(self.handler.parse_string(self.sample_ass_content))
        
        log_input_expected_result(self.sample_ass_content[:100] + "...", len(self.expected_lines), len(lines))
        
        self.assertEqual(len(lines), len(self.expected_lines))
        
        for i, (expected, actual) in enumerate(zip(self.expected_lines, lines)):
            with self.subTest(line_number=i+1):
                self.assertEqual(actual.number, expected.number)
                self.assertEqual(actual.start, expected.start)
                self.assertEqual(actual.end, expected.end)
                # pysubs2 preserves \\N as literal \\N, not converted to newlines
                if expected.text and "\n" in expected.text:
                    expected_text = expected.text.replace("\n", "\\N")
                else:
                    expected_text = expected.text
                self.assertEqual(actual.text, expected_text)
                self.assertEqual(actual.metadata['format'], expected.metadata['format'])
                self.assertEqual(actual.metadata['style'], expected.metadata['style'])
    
    def test_parse_file(self):
        """Test parsing from file object."""
        log_test_name("AssFileHandler.parse_file")
        
        file_obj = StringIO(self.sample_ass_content)
        lines = list(self.handler.parse_file(file_obj))
        
        log_input_expected_result("File content", 3, len(lines))
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0].text, "First subtitle line")
    
    def test_ass_time_conversion(self):
        """Test ASS time format conversion."""
        log_test_name("AssTimeToTimedelta")
        
        test_cases = [
            ("0:00:01.50", timedelta(seconds=1, milliseconds=500)),
            ("0:01:30.00", timedelta(minutes=1, seconds=30)),
            ("1:05:45.25", timedelta(hours=1, minutes=5, seconds=45, milliseconds=250)),
            ("0:00:00.00", timedelta(seconds=0)),
        ]
        
        for ass_time, expected_delta in test_cases:
            with self.subTest(ass_time=ass_time):
                result = AssTimeToTimedelta(ass_time)
                log_input_expected_result(ass_time, expected_delta, result)
                self.assertEqual(result, expected_delta)
    
    def test_timedelta_to_ass_time(self):
        """Test timedelta to ASS time format conversion."""
        log_test_name("TimedeltaToAssTime")
        
        test_cases = [
            (timedelta(seconds=1, milliseconds=500), "0:00:01.50"),
            (timedelta(minutes=1, seconds=30), "0:01:30.00"),
            (timedelta(hours=1, minutes=5, seconds=45, milliseconds=250), "1:05:45.25"),
            (timedelta(seconds=0), "0:00:00.00"),
        ]
        
        for delta, expected_ass_time in test_cases:
            with self.subTest(timedelta=delta):
                result = TimedeltaToAssTime(delta)
                log_input_expected_result(str(delta), expected_ass_time, result)
                self.assertEqual(result, expected_ass_time)
    
    def test_compose_lines_basic(self):
        """Test basic line composition to ASS format."""
        log_test_name("AssFileHandler.compose_lines - basic")
        
        lines = [
            SubtitleLine.Construct(
                number=1,
                start=timedelta(seconds=1, milliseconds=500),
                end=timedelta(seconds=3),
                text="Test subtitle",
                metadata={'format': 'ass', 'style': 'Default', 'layer': 0, 'name': '', 
                         'margin_l': 0, 'margin_r': 0, 'margin_v': 0, 'effect': ''}
            )
        ]
        
        result = self.handler.compose_lines(lines)
        
        # Check that the result contains key ASS sections
        self.assertIn("[Script Info]", result)
        self.assertIn("[V4+ Styles]", result)
        self.assertIn("[Events]", result)
        self.assertIn("Dialogue: 0,0:00:01.50,0:00:03.00,Default,,0,0,0,,Test subtitle", result)
        
        log_input_expected_result("1 line", "ASS format with all sections", "X Contains all sections")
    
    def test_compose_lines_with_line_breaks(self):
        """Test composition with line breaks."""
        log_test_name("AssFileHandler.compose_lines - line breaks")
        
        lines = [
            SubtitleLine.Construct(
                number=1,
                start=timedelta(seconds=1),
                end=timedelta(seconds=3),
                text="First line\nSecond line",
                metadata={'format': 'ass', 'style': 'Default', 'layer': 0, 'name': '', 
                         'margin_l': 0, 'margin_r': 0, 'margin_v': 0, 'effect': ''}
            )
        ]
        
        result = self.handler.compose_lines(lines)
        
        # pysubs2 preserves line breaks as actual newlines in output, not \\N
        expected_text = "First line\nSecond line"
        contains_expected = expected_text in result
        log_input_expected_result("Contains line break text", True, contains_expected)
        self.assertIn(expected_text, result)
    
    def test_parse_empty_events_section(self):
        """Test parsing ASS file with no events."""
        log_test_name("AssFileHandler.parse_string - no events")
        
        content_no_events = """[Script Info]
Title: Test

[V4+ Styles]
Format: Name, Fontname, Fontsize
Style: Default,Arial,50

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        
        lines = list(self.handler.parse_string(content_no_events))
        
        log_input_expected_result("ASS with no dialogue lines", 0, len(lines))
        self.assertEqual(len(lines), 0)
    
    def test_parse_invalid_ass_content(self):
        """Test error handling for invalid ASS content."""
        log_test_name("AssFileHandler.parse_string - invalid content")
        
        invalid_content = """This is not ASS format content"""
        
        with self.assertRaises(SubtitleParseError):
            list(self.handler.parse_string(invalid_content))
        
        log_input_expected_result("Invalid content", "SubtitleParseError", "X Exception raised")
    
    
    def test_reindex_functionality(self):
        """Test reindexing functionality in compose_lines."""
        log_test_name("AssFileHandler.compose_lines - reindex")
        
        lines = [
            SubtitleLine.Construct(
                number=10,  # Original index
                start=timedelta(seconds=1),
                end=timedelta(seconds=2),
                text="Test",
                metadata={'format': 'ass', 'style': 'Default', 'layer': 0, 'name': '', 
                         'margin_l': 0, 'margin_r': 0, 'margin_v': 0, 'effect': ''}
            )
        ]
        
        result_reindex = self.handler.compose_lines(lines, reindex=True)
        result_no_reindex = self.handler.compose_lines(lines, reindex=False)
        
        # When reindexing, should start from 1
        # When not reindexing, should preserve original number
        # Note: ASS doesn't have explicit line numbers in dialogue lines like SRT,
        # so we just verify the output is generated without errors
        
        self.assertIsInstance(result_reindex, str)
        self.assertIsInstance(result_no_reindex, str)
        self.assertIn("Dialogue:", result_reindex)
        self.assertIn("Dialogue:", result_no_reindex)
        
        log_input_expected_result("Reindex test", "Both formats generated", "✓ Both options work")
    
    def test_round_trip_conversion(self):
        """Test that parsing and composing results in similar content."""
        log_test_name("AssFileHandler round-trip conversion")
        
        # Parse the sample content
        original_lines = list(self.handler.parse_string(self.sample_ass_content))
        
        # Compose back to ASS format
        composed = self.handler.compose_lines(original_lines)
        
        # Parse the composed content again
        round_trip_lines = list(self.handler.parse_string(composed))
        
        log_input_expected_result("Original lines", len(original_lines), len(round_trip_lines))
        self.assertEqual(len(original_lines), len(round_trip_lines))
        
        # Compare key properties
        for original, round_trip in zip(original_lines, round_trip_lines):
            self.assertEqual(original.start, round_trip.start)
            self.assertEqual(original.end, round_trip.end)
            self.assertEqual(original.text, round_trip.text)

if __name__ == '__main__':
    unittest.main()