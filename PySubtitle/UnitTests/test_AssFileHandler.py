import unittest
from io import StringIO
from datetime import timedelta

from PySubtitle.Formats.AssFileHandler import AssFileHandler
from PySubtitle.SubtitleLine import SubtitleLine
from PySubtitle.SubtitleData import SubtitleData
from PySubtitle.SubtitleError import SubtitleParseError
from PySubtitle.Helpers.Tests import log_info, log_input_expected_result, log_test_name, skip_if_debugger_attached

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
        
        data = self.handler.parse_string(self.sample_ass_content)
        lines = data.lines
        
        log_input_expected_result(self.sample_ass_content[:100] + "...", len(self.expected_lines), len(lines))
        
        self.assertEqual(len(lines), len(self.expected_lines))
        
        for i, (expected, actual) in enumerate(zip(self.expected_lines, lines)):
            with self.subTest(line_number=i+1):
                self.assertEqual(actual.number, expected.number)
                self.assertEqual(actual.start, expected.start)
                self.assertEqual(actual.end, expected.end)
                # pysubs2 plaintext property converts \\N to \n for GUI compatibility
                self.assertEqual(actual.text, expected.text)
                self.assertEqual(actual.metadata['format'], expected.metadata['format'])
                self.assertEqual(actual.metadata['style'], expected.metadata['style'])
    
    def test_parse_file(self):
        """Test parsing from file object."""
        log_test_name("AssFileHandler.parse_file")
        
        file_obj = StringIO(self.sample_ass_content)
        data = self.handler.parse_file(file_obj)
        lines = data.lines
        
        log_input_expected_result("File content", 3, len(lines))
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0].text, "First subtitle line")
    
    
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
        
        data = SubtitleData(lines=lines, metadata={'format': 'ass'})
        result = self.handler.compose(data)
        
        # Log before assertions
        expected_sections = ["[Script Info]", "[V4+ Styles]", "[Events]", "Dialogue: 0,0:00:01.50,0:00:03.00,Default,,0,0,0,,Test subtitle"]
        has_all_sections = all(section in result for section in expected_sections)
        log_input_expected_result("1 line", True, has_all_sections)
        
        # Check that the result contains key ASS sections
        self.assertIn("[Script Info]", result)
        self.assertIn("[V4+ Styles]", result)
        self.assertIn("[Events]", result)
        self.assertIn("Dialogue: 0,0:00:01.50,0:00:03.00,Default,,0,0,0,,Test subtitle", result)
    
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
        
        data = SubtitleData(lines=lines, metadata={'format': 'ass'})
        result = self.handler.compose(data)
        
        # pysubs2 converts newlines back to \\N in ASS format output
        expected_text = "First line\\NSecond line"
        contains_expected = expected_text in result
        log_input_expected_result("Contains ASS line break", True, contains_expected)
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
        
        data = self.handler.parse_string(content_no_events)
        lines = data.lines
        
        log_input_expected_result("ASS with no dialogue lines", 0, len(lines))
        self.assertEqual(len(lines), 0)
    
    def test_parse_invalid_ass_content(self):
        """Test error handling for invalid ASS content."""
        if skip_if_debugger_attached("test_parse_invalid_ass_content"):
            return
            
        log_test_name("AssFileHandler.parse_string - invalid content")
        
        invalid_content = """This is not ASS format content"""
        
        assert_raised : bool = True
        with self.assertRaises(SubtitleParseError):
            self.handler.parse_string(invalid_content)
            assert_raised = False
        
        log_input_expected_result("Invalid content", True, assert_raised)
    
    
    def test_round_trip_conversion(self):
        """Test that parsing and composing results in similar content."""
        log_test_name("AssFileHandler round-trip conversion")
        
        # Parse the sample content
        original_data = self.handler.parse_string(self.sample_ass_content)
        original_lines = original_data.lines
        
        # Compose back to ASS format using original metadata
        composed = self.handler.compose(original_data)
        
        # Parse the composed content again
        round_trip_data = self.handler.parse_string(composed)
        round_trip_lines = round_trip_data.lines
        
        log_input_expected_result("Original lines", len(original_lines), len(round_trip_lines))
        self.assertEqual(len(original_lines), len(round_trip_lines))
        
        # Validate metadata preservation
        self.assertEqual(original_data.metadata['format'], round_trip_data.metadata['format'])
        self.assertIn('styles', original_data.metadata)
        self.assertIn('styles', round_trip_data.metadata)
        self.assertEqual(original_data.metadata['styles'], round_trip_data.metadata['styles'])
        log_input_expected_result("Metadata preserved", True, True)
        
        # Compare line properties
        for original, round_trip in zip(original_lines, round_trip_lines):
            self.assertEqual(original.start, round_trip.start)
            self.assertEqual(original.end, round_trip.end)
            self.assertEqual(original.text, round_trip.text)
    
    def test_subtitle_line_to_pysubs2_time_conversion(self):
        """Test that _subtitle_line_to_pysubs2 correctly converts timedelta to pysubs2 milliseconds."""
        log_test_name("AssFileHandler._subtitle_line_to_pysubs2 - time conversion")
        
        # Test various time formats with precise timedelta values
        test_cases = [
            # (timedelta, expected_milliseconds)
            (timedelta(seconds=1, milliseconds=500), 1500),
            (timedelta(seconds=30), 30000),
            (timedelta(minutes=1, seconds=30, milliseconds=250), 90250),
            (timedelta(hours=1, minutes=23, seconds=45, milliseconds=678), 5025678),
            (timedelta(microseconds=500000), 500),  # 0.5 seconds
        ]
        
        for i, (test_timedelta, expected_ms) in enumerate(test_cases):
            with self.subTest(case=i):
                # Create a test SubtitleLine
                test_line = SubtitleLine.Construct(
                    number=1,
                    start=test_timedelta,
                    end=test_timedelta + timedelta(seconds=2),
                    text="Test",
                    metadata={'format': 'ass', 'style': 'Default', 'layer': 0, 'name': '', 
                             'margin_l': 0, 'margin_r': 0, 'margin_v': 0, 'effect': ''}
                )
                
                # Convert to pysubs2 event
                pysubs2_event = self.handler._subtitle_line_to_pysubs2(test_line)
                
                log_input_expected_result(f"Timedelta {test_timedelta}", expected_ms, pysubs2_event.start)
                self.assertEqual(pysubs2_event.start, expected_ms)

if __name__ == '__main__':
    unittest.main()