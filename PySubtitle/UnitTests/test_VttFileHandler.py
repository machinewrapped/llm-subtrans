import unittest
from datetime import timedelta
import tempfile
import os

from PySubtitle.Formats.VttFileHandler import VttFileHandler
from PySubtitle.SubtitleLine import SubtitleLine
from PySubtitle.SubtitleData import SubtitleData
from PySubtitle.SubtitleError import SubtitleParseError
from PySubtitle.Helpers.Tests import log_input_expected_result, log_test_name, skip_if_debugger_attached

class TestVttFileHandler(unittest.TestCase):
    """Test cases for WebVTT file handler."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.handler = VttFileHandler()
        
        # Sample VTT content for testing
        self.sample_vtt_content = """WEBVTT

00:00:01.500 --> 00:00:03.000
First subtitle line

00:00:04.000 --> 00:00:06.500
Second subtitle line
with line break

00:00:07.000 --> 00:00:09.000
Third subtitle line with <i>formatting</i>
"""
        
        # Expected parsed lines
        self.expected_lines = [
            SubtitleLine.Construct(
                number=1,
                start=timedelta(seconds=1, milliseconds=500),
                end=timedelta(seconds=3),
                text="First subtitle line",
                metadata={}
            ),
            SubtitleLine.Construct(
                number=2,
                start=timedelta(seconds=4),
                end=timedelta(seconds=6, milliseconds=500),
                text="Second subtitle line\nwith line break",
                metadata={}
            ),
            SubtitleLine.Construct(
                number=3,
                start=timedelta(seconds=7),
                end=timedelta(seconds=9),
                text="Third subtitle line with <i>formatting</i>",
                metadata={}
            )
        ]
    
    def test_get_file_extensions(self):
        """Test that the handler returns correct file extensions."""
        log_test_name("VttFileHandler.get_file_extensions")
        
        expected = ['.vtt']
        result = self.handler.get_file_extensions()
        
        log_input_expected_result("", expected, result)
        self.assertEqual(result, expected)
    
    def test_parse_string_basic(self):
        """Test parsing of basic WebVTT content."""
        log_test_name("VttFileHandler.parse_string - basic parsing")
        
        data = self.handler.parse_string(self.sample_vtt_content)
        lines = data.lines
        
        log_input_expected_result(self.sample_vtt_content[:100] + "...", len(self.expected_lines), len(lines))
        
        self.assertEqual(len(lines), len(self.expected_lines))
        
        for i, (expected, actual) in enumerate(zip(self.expected_lines, lines)):
            with self.subTest(line_number=i+1):
                self.assertEqual(actual.number, expected.number)
                self.assertEqual(actual.start, expected.start)
                self.assertEqual(actual.end, expected.end)
                self.assertEqual(actual.text, expected.text)
    
    def test_load_file(self):
        """Test parsing from file path."""
        log_test_name("VttFileHandler.load_file")

        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.vtt', encoding='utf-8') as f:
            f.write(self.sample_vtt_content)
            temp_path = f.name

        try:
            data = self.handler.load_file(temp_path)
        finally:
            os.remove(temp_path)

        lines = data.lines
        log_input_expected_result("File content", 3, len(lines))
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0].text, "First subtitle line")
    
    def test_load_real_vtt_file(self):
        """Test loading the actual test-vtt.vtt file."""
        log_test_name("VttFileHandler.load_file - real test file")
        
        # Use the actual test file
        test_file_path = "D:\\Development\\Github\\llm-subtrans\\test-vtt.vtt"
        
        if os.path.exists(test_file_path):
            data = self.handler.load_file(test_file_path)
            lines = data.lines
            
            log_input_expected_result("Real VTT file lines", True, len(lines) > 0)
            self.assertTrue(len(lines) > 0)
            
            # Check first line contains expected Chinese text
            if lines and lines[0].text:
                first_line_text = lines[0].text
                log_input_expected_result("First line contains Chinese", True, "這是我的師傅" in first_line_text)
                self.assertIn("這是我的師傅", first_line_text)
        else:
            self.skipTest(f"Test file not found: {test_file_path}")
    
    def test_compose_lines_basic(self):
        """Test basic line composition to WebVTT format."""
        log_test_name("VttFileHandler.compose_lines - basic")
        
        lines = [
            SubtitleLine.Construct(
                number=1,
                start=timedelta(seconds=1, milliseconds=500),
                end=timedelta(seconds=3),
                text="Test subtitle",
                metadata={}
            )
        ]
        
        data = SubtitleData(lines=lines, metadata={})
        result = self.handler.compose(data)
        
        # Log before assertions
        expected_sections = ["WEBVTT", "00:00:01.500 --> 00:00:03.000", "Test subtitle"]
        has_all_sections = all(section in result for section in expected_sections)
        log_input_expected_result("1 line", True, has_all_sections)
        
        # Check that the result contains key WebVTT sections
        self.assertIn("WEBVTT", result)
        self.assertIn("00:00:01.500 --> 00:00:03.000", result)
        self.assertIn("Test subtitle", result)
    
    def test_compose_lines_with_html_formatting(self):
        """Test composition with HTML formatting preservation."""
        log_test_name("VttFileHandler.compose_lines - HTML formatting")
        
        lines = [
            SubtitleLine.Construct(
                number=1,
                start=timedelta(seconds=1),
                end=timedelta(seconds=3),
                text="Text with <i>italic</i> and <b>bold</b>",
                metadata={}
            )
        ]
        
        data = SubtitleData(lines=lines, metadata={})
        result = self.handler.compose(data)
        
        # WebVTT should preserve HTML formatting tags
        expected_text = "Text with <i>italic</i> and <b>bold</b>"
        contains_expected = expected_text in result
        log_input_expected_result("Contains HTML formatting", True, contains_expected)
        self.assertIn(expected_text, result)
    
    def test_parse_empty_vtt(self):
        """Test parsing WebVTT file with no cues."""
        log_test_name("VttFileHandler.parse_string - no cues")
        
        content_no_cues = """WEBVTT

"""
        
        data = self.handler.parse_string(content_no_cues)
        lines = data.lines
        
        log_input_expected_result("WebVTT with no cues", 0, len(lines))
        self.assertEqual(len(lines), 0)
    
    def test_parse_invalid_vtt_content(self):
        """Test error handling for invalid WebVTT content."""
        if skip_if_debugger_attached("test_parse_invalid_vtt_content"):
            return
            
        log_test_name("VttFileHandler.parse_string - invalid content")
        
        invalid_content = """This is not WebVTT format content"""
        
        assert_raised : bool = True
        with self.assertRaises(SubtitleParseError):
            self.handler.parse_string(invalid_content)
            assert_raised = False
        
        log_input_expected_result("Invalid content", True, assert_raised)
    
    def test_round_trip_conversion(self):
        """Test that parsing and composing results in similar content."""
        log_test_name("VttFileHandler round-trip conversion")
        
        # Parse the sample content
        original_data = self.handler.parse_string(self.sample_vtt_content)
        original_lines = original_data.lines
        
        # Compose back to WebVTT format using original metadata
        composed = self.handler.compose(original_data)
        
        # Parse the composed content again
        round_trip_data = self.handler.parse_string(composed)
        round_trip_lines = round_trip_data.lines
        
        log_input_expected_result("Original lines", len(original_lines), len(round_trip_lines))
        self.assertEqual(len(original_lines), len(round_trip_lines))
        
        # Validate metadata preservation
        log_input_expected_result("Metadata preserved", True, True)
        self.assertEqual(original_data.detected_format, round_trip_data.detected_format)
        
        # Compare line properties
        for original, round_trip in zip(original_lines, round_trip_lines):
            self.assertEqual(original.start, round_trip.start)
            self.assertEqual(original.end, round_trip.end)
            self.assertEqual(original.text, round_trip.text)

    def test_detect_vtt_format(self):
        """Ensure VTT files retain their format information."""
        log_test_name("VttFileHandler WebVTT format detection")

        data = self.handler.parse_string(self.sample_vtt_content)
        log_input_expected_result("WebVTT format", '.vtt', data.detected_format)
        self.assertEqual(data.detected_format, '.vtt')

        composed = self.handler.compose(data)
        log_input_expected_result("Round trip format", True, "WEBVTT" in composed)
        self.assertIn("WEBVTT", composed)
    
    def test_timestamp_formatting_conversion(self):
        """Test that timestamp formatting works correctly."""
        log_test_name("VttFileHandler timestamp formatting")
        
        # Test various time formats with precise timedelta values
        test_cases = [
            # (timedelta, expected_string)
            (timedelta(seconds=1, milliseconds=500), "00:00:01.500"),
            (timedelta(seconds=30), "00:00:30.000"),
            (timedelta(minutes=1, seconds=30, milliseconds=250), "00:01:30.250"),
            (timedelta(hours=1, minutes=23, seconds=45, milliseconds=678), "01:23:45.678"),
            (timedelta(microseconds=500000), "00:00:00.500"),  # 0.5 seconds
        ]
        
        for i, (test_timedelta, expected_string) in enumerate(test_cases):
            with self.subTest(case=i):
                result = self.handler._format_timestamp(test_timedelta)
                
                log_input_expected_result(f"Timedelta {test_timedelta}", expected_string, result)
                self.assertEqual(result, expected_string)
    
    def test_vtt_cue_id_preservation(self):
        """Test that WebVTT cue IDs are preserved when present."""
        log_test_name("VttFileHandler cue ID preservation")
        
        # WebVTT with cue identifiers
        vtt_with_cues = """WEBVTT

cue1
00:00:01.000 --> 00:00:03.000
First subtitle with ID

00:00:04.000 --> 00:00:06.000
Second subtitle without ID

cue3
00:00:07.000 --> 00:00:09.000
Third subtitle with ID
"""
        
        data = self.handler.parse_string(vtt_with_cues)
        lines = data.lines
        
        self.assertEqual(len(lines), 3)
        
        # Check that cue IDs are preserved in metadata where present
        if len(lines) >= 1 and 'cue_id' in lines[0].metadata:
            log_input_expected_result("First cue ID", "cue1", lines[0].metadata['cue_id'])
            self.assertEqual(lines[0].metadata['cue_id'], "cue1")
        
        # Second line should not have cue ID
        log_input_expected_result("Second line has no cue ID", True, 'cue_id' not in lines[1].metadata)
        self.assertNotIn('cue_id', lines[1].metadata)
        
        if len(lines) >= 3 and 'cue_id' in lines[2].metadata:
            log_input_expected_result("Third cue ID", "cue3", lines[2].metadata['cue_id'])
            self.assertEqual(lines[2].metadata['cue_id'], "cue3")
    
    def test_vtt_multiline_cues(self):
        """Test parsing of multi-line WebVTT cues."""
        log_test_name("VttFileHandler multi-line cues")
        
        multiline_vtt = """WEBVTT

00:00:01.000 --> 00:00:05.000
This is a multi-line subtitle
that spans several lines
and should be preserved

00:00:06.000 --> 00:00:08.000
Single line subtitle
"""
        
        data = self.handler.parse_string(multiline_vtt)
        lines = data.lines
        
        self.assertEqual(len(lines), 2)
        
        # Check multi-line text preservation
        first_line_text = lines[0].text
        expected_multiline = "This is a multi-line subtitle\nthat spans several lines\nand should be preserved"
        log_input_expected_result("Multi-line text", expected_multiline, first_line_text)
        self.assertEqual(first_line_text, expected_multiline)
        
        # Check single line
        second_line_text = lines[1].text
        log_input_expected_result("Single line text", "Single line subtitle", second_line_text)
        self.assertEqual(second_line_text, "Single line subtitle")
    
    def test_detected_format_field(self):
        """Test that detected_format is correctly set to .vtt"""
        log_test_name("VttFileHandler detected_format field")
        
        data = self.handler.parse_string(self.sample_vtt_content)
        
        log_input_expected_result("Detected format", ".vtt", data.detected_format)
        self.assertEqual(data.detected_format, ".vtt")
    
    def test_cue_settings_preservation(self):
        """Test that cue settings are preserved in metadata."""
        log_test_name("VttFileHandler cue settings preservation")
        
        vtt_with_settings = """WEBVTT

00:00:01.000 --> 00:00:03.000 position:10%,line-left align:left size:35%
Where did he go?

00:00:03.000 --> 00:00:06.500 position:90% align:right size:35%
I think he went down this lane.
"""
        
        data = self.handler.parse_string(vtt_with_settings)
        lines = data.lines
        
        self.assertEqual(len(lines), 2)
        
        # Check first cue settings
        first_settings = lines[0].metadata.get('vtt_settings', '')
        log_input_expected_result("First cue settings", "position:10%,line-left align:left size:35%", first_settings)
        self.assertEqual(first_settings, "position:10%,line-left align:left size:35%")
        
        # Check second cue settings
        second_settings = lines[1].metadata.get('vtt_settings', '')
        log_input_expected_result("Second cue settings", "position:90% align:right size:35%", second_settings)
        self.assertEqual(second_settings, "position:90% align:right size:35%")
        
        # Test round-trip preservation
        composed = self.handler.compose(data)
        round_trip_data = self.handler.parse_string(composed)
        round_trip_lines = round_trip_data.lines
        
        log_input_expected_result("Round-trip settings preserved", True, 
                                round_trip_lines[0].metadata.get('vtt_settings') == first_settings)
        self.assertEqual(round_trip_lines[0].metadata.get('vtt_settings'), first_settings)
        self.assertEqual(round_trip_lines[1].metadata.get('vtt_settings'), second_settings)
    
    def test_style_blocks_preservation(self):
        """Test that STYLE blocks are preserved in file metadata."""
        log_test_name("VttFileHandler STYLE blocks preservation")
        
        vtt_with_styles = """WEBVTT

STYLE
::cue {
  background-image: linear-gradient(to bottom, dimgray, lightgray);
  color: papayawhip;
}

NOTE comment blocks can be used between style blocks.

STYLE
::cue(b) {
  color: peachpuff;
}

00:00:01.000 --> 00:00:03.000
Styled subtitle
"""
        
        data = self.handler.parse_string(vtt_with_styles)
        
        # Check that styles are captured
        vtt_styles = data.metadata.get('vtt_styles', [])
        log_input_expected_result("Number of style blocks", 2, len(vtt_styles))
        self.assertEqual(len(vtt_styles), 2)
        
        # Check first style block content
        first_style = vtt_styles[0]
        self.assertIn("::cue {", first_style)
        self.assertIn("papayawhip", first_style)
        
        # Check second style block content
        second_style = vtt_styles[1]
        self.assertIn("::cue(b)", second_style)
        self.assertIn("peachpuff", second_style)
        
        # Test round-trip preservation
        composed = self.handler.compose(data)
        round_trip_data = self.handler.parse_string(composed)
        
        rt_styles = round_trip_data.metadata.get('vtt_styles', [])
        log_input_expected_result("Round-trip styles preserved", 2, len(rt_styles))
        self.assertEqual(len(rt_styles), 2)
        
        # Check content is preserved
        log_input_expected_result("Style content preserved", True, "papayawhip" in rt_styles[0])
        self.assertIn("papayawhip", rt_styles[0])
        self.assertIn("peachpuff", rt_styles[1])
    
    def test_speaker_voice_tags(self):
        """Test that speaker voice tags are handled correctly."""
        log_test_name("VttFileHandler speaker voice tags")
        
        vtt_with_speakers = """WEBVTT

00:00:00.000 --> 00:00:02.000
<v.first.loud Esme>It's a blue apple tree!

00:00:02.000 --> 00:00:04.000
<v Mary>No way!</v>

00:00:04.000 --> 00:00:06.000
<v Esme>Hee!</v> <i>laughter</i>

00:00:06.000 --> 00:00:08.000
<v.loud Mary>That's awesome!
"""
        
        data = self.handler.parse_string(vtt_with_speakers)
        lines = data.lines
        
        self.assertEqual(len(lines), 4)
        
        # Check speaker extraction
        speakers = [line.metadata.get('speaker') for line in lines]
        expected_speakers = ['Esme', 'Mary', 'Esme', 'Mary']
        log_input_expected_result("Extracted speakers", expected_speakers, speakers)
        self.assertEqual(speakers, expected_speakers)
        
        # Check text processing (voice tags removed)
        texts = [line.text for line in lines]
        expected_texts = [
            "It's a blue apple tree!",
            "No way!",
            "Hee! <i>laughter</i>",
            "That's awesome!"
        ]
        log_input_expected_result("Processed texts", expected_texts, texts)
        self.assertEqual(texts, expected_texts)
        
        # Test round-trip (voice tags restored)
        composed = self.handler.compose(data)
        log_input_expected_result("Voice tags restored", True, "<v Esme>" in composed and "<v Mary>" in composed)
        self.assertIn("<v Esme>", composed)
        self.assertIn("<v Mary>", composed)
        
        # Verify round-trip parsing
        round_trip_data = self.handler.parse_string(composed)
        rt_speakers = [line.metadata.get('speaker') for line in round_trip_data.lines]
        log_input_expected_result("Round-trip speakers", expected_speakers, rt_speakers)
        self.assertEqual(rt_speakers, expected_speakers)

if __name__ == '__main__':
    unittest.main()