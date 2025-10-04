import unittest
from datetime import timedelta
import tempfile
import os

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Formats.VttFileHandler import VttFileHandler
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.SubtitleData import SubtitleData
from PySubtrans.SubtitleError import SubtitleParseError
from PySubtrans.Helpers.Tests import (
    log_test_name,
    skip_if_debugger_attached,
)

class TestVttFileHandler(LoggedTestCase):
    """Test cases for WebVTT file handler."""
    
    def setUp(self) -> None:
        """Set up test fixtures."""
        super().setUp()
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
        
        expected = ['.vtt']
        result = self.handler.get_file_extensions()
        
        self.assertLoggedEqual("VTT extensions", expected, result)
    
    def test_parse_string_basic(self):
        """Test parsing of basic WebVTT content."""
        
        data = self.handler.parse_string(self.sample_vtt_content)
        lines = data.lines
        
        self.assertLoggedEqual("Parsed line count", len(self.expected_lines), len(lines))
        
        
        for i, (expected, actual) in enumerate(zip(self.expected_lines, lines)):
            with self.subTest(line_number=i+1):
                self.assertEqual(actual.number, expected.number)
                self.assertEqual(actual.start, expected.start)
                self.assertEqual(actual.end, expected.end)
                self.assertEqual(actual.text, expected.text)
    
    def test_load_file(self):
        """Test parsing from file path."""

        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.vtt', encoding='utf-8') as f:
            f.write(self.sample_vtt_content)
            temp_path = f.name

        try:
            data = self.handler.load_file(temp_path)
        finally:
            os.remove(temp_path)

        lines = data.lines
        self.assertLoggedEqual('File content', 3, len(lines))
        self.assertEqual(lines[0].text, "First subtitle line")

    def test_composition_variations(self):
        """Test composition of various WebVTT scenarios."""
        
        test_cases = [
            {
                "test_name": "basic_composition",
                "lines": [
                    SubtitleLine.Construct(
                        number=1,
                        start=timedelta(seconds=1, milliseconds=500),
                        end=timedelta(seconds=3),
                        text="Test subtitle",
                        metadata={}
                    )
                ],
                "metadata": {},
                "should_contain": ["WEBVTT", "00:00:01.500 --> 00:00:03.000", "Test subtitle"]
            },
            {
                "test_name": "html_formatting",
                "lines": [
                    SubtitleLine.Construct(
                        number=1,
                        start=timedelta(seconds=1),
                        end=timedelta(seconds=3),
                        text="Text with <i>italic</i> and <b>bold</b>",
                        metadata={}
                    )
                ],
                "metadata": {},
                "should_contain": ["Text with <i>italic</i> and <b>bold</b>"]
            },
            {
                "test_name": "cue_id",
                "lines": [
                    SubtitleLine.Construct(
                        number=1,
                        start=timedelta(seconds=1),
                        end=timedelta(seconds=3),
                        text="First line",
                        metadata={"cue_id": "cue1"}
                    )
                ],
                "metadata": {},
                "should_contain": ["cue1", "First line"]
            },
            {
                "test_name": "cue_settings",
                "lines": [
                    SubtitleLine.Construct(
                        number=1,
                        start=timedelta(seconds=1),
                        end=timedelta(seconds=3),
                        text="Where did he go?",
                        metadata={"vtt_settings": "position:10% align:left size:35%"}
                    )
                ],
                "metadata": {},
                "should_contain": ["position:10% align:left size:35%", "Where did he go?"]
            },
            {
                "test_name": "voice_tags",
                "lines": [
                    SubtitleLine.Construct(
                        number=1,
                        start=timedelta(seconds=1),
                        end=timedelta(seconds=3),
                        text="Hello world",
                        metadata={"speaker": "Mary", "voice_classes": ["loud"]}
                    )
                ],
                "metadata": {},
                "should_contain": ["<v.loud Mary>Hello world</v>"]
            },
            {
                "test_name": "metadata_blocks",
                "lines": [],
                "metadata": {
                    "vtt_styles": ["::cue {\n  color: red;\n}"],
                    "vtt_notes": ["This is a test note"]
                },
                "should_contain": ["WEBVTT", "STYLE", "::cue", "color: red", "NOTE", "This is a test note"]
            }
        ]
        
        for case in test_cases:
            with self.subTest(test_name=case["test_name"]):
                log_test_name(f'VttFileHandler composition - {case["test_name"]}')
                data = SubtitleData(lines=case["lines"], metadata=case["metadata"])
                result = self.handler.compose(data)
                
                for expected_content in case["should_contain"]:
                    contains_content = expected_content in result
                    self.assertLoggedIn(expected_content, expected_content, result)
    
    @skip_if_debugger_attached
    def test_parse_invalid_vtt_content(self):
        """Test error handling for invalid WebVTT content."""
        
        invalid_content = """This is not WebVTT format content"""
        
        assert_raised : bool = True
        with self.assertRaises(SubtitleParseError):
            self.handler.parse_string(invalid_content)
            assert_raised = False
        
        self.assertLoggedTrue('Invalid content', assert_raised)
    
    
    def test_round_trip_conversion(self):
        """Test that parsing and composing results in similar content."""
        
        # Parse the sample content
        original_data = self.handler.parse_string(self.sample_vtt_content)
        original_lines = original_data.lines
        
        # Compose back to WebVTT format using original metadata
        composed = self.handler.compose(original_data)
        
        # Parse the composed content again
        round_trip_data = self.handler.parse_string(composed)
        round_trip_lines = round_trip_data.lines
        
        self.assertLoggedEqual('Original lines', len(original_lines), len(round_trip_lines))
        
        # Validate metadata preservation
        self.assertLoggedEqual("Metadata format preserved", original_data.detected_format, round_trip_data.detected_format)
        
        # Compare line properties
        for original, round_trip in zip(original_lines, round_trip_lines):
            self.assertEqual(original.start, round_trip.start)
            self.assertEqual(original.end, round_trip.end)
            self.assertEqual(original.text, round_trip.text)

    def test_detect_vtt_format(self):
        """Ensure VTT files retain their format information."""

        data = self.handler.parse_string(self.sample_vtt_content)

        self.assertLoggedEqual('Detected format', '.vtt', data.detected_format)

        composed = self.handler.compose(data)
        self.assertLoggedIn('Round trip format', 'WEBVTT', composed)
    
    def test_timestamp_formatting_conversion(self):
        """Test that timestamp formatting works correctly."""
        
        # Test various time formats with precise timedelta values
        test_cases = [
            (timedelta(seconds=1, milliseconds=500), "00:00:01.500"),
            (timedelta(seconds=30), "00:00:30.000"),
            (timedelta(minutes=1, seconds=30, milliseconds=250), "00:01:30.250"),
            (timedelta(hours=1, minutes=23, seconds=45, milliseconds=678), "01:23:45.678"),
            (timedelta(microseconds=500000), "00:00:00.500"),
            (timedelta(0), "00:00:00.000"),
            (timedelta(milliseconds=1), "00:00:00.001"),
            (timedelta(milliseconds=999), "00:00:00.999"),
            (timedelta(seconds=59, milliseconds=999), "00:00:59.999"),
            (timedelta(hours=23, minutes=59, seconds=59, milliseconds=999), "23:59:59.999"),
        ]
        
        for i, (test_timedelta, expected_string) in enumerate(test_cases):
            with self.subTest(case=i):
                result = self.handler._format_timestamp(test_timedelta)
                
                self.assertLoggedEqual(test_timedelta, expected_string, result)
    
    def test_vtt_cue_id_preservation(self):
        """Test that WebVTT cue IDs are preserved when present."""
        
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
            self.assertLoggedEqual('First cue ID', 'cue1', lines[0].metadata['cue_id'])
        
        # Second line should not have cue ID
        self.assertLoggedNotIn('Second line has no cue ID', 'cue_id', lines[1].metadata)
        
        if len(lines) >= 3 and 'cue_id' in lines[2].metadata:
            self.assertLoggedEqual('Third cue ID', 'cue3', lines[2].metadata['cue_id'])
    

    def test_vtt_parsing_variations(self):
        """Test parsing of various WebVTT content formats."""
        test_cases = [
            {
                "test_name": "empty_vtt",
                "content": """WEBVTT

""",
                "expected_lines": 0,
                "check_format": True
            },
            {
                "test_name": "no_hour_timestamp",
                "content": """WEBVTT

00:01.500 --> 00:03.000
No hour field
""",
                "expected_lines": 1,
                "first_start": timedelta(seconds=1, milliseconds=500),
                "first_text": "No hour field"
            },
            {
                "test_name": "multiline_cues",
                "content": """WEBVTT

00:00:01.000 --> 00:00:05.000
This is a multi-line subtitle
that spans several lines
and should be preserved

00:00:06.000 --> 00:00:08.000
Single line subtitle
""",
                "expected_lines": 2,
                "first_text": "This is a multi-line subtitle\nthat spans several lines\nand should be preserved",
                "second_text": "Single line subtitle"
            },
            {
                "test_name": "cue_ids",
                "content": """WEBVTT

cue1
00:00:01.000 --> 00:00:03.000
First subtitle with ID

00:00:04.000 --> 00:00:06.000
Second subtitle without ID
""",
                "expected_lines": 2,
                "first_cue_id": "cue1",
                "second_no_cue_id": True
            },
            {
                "test_name": "cue_settings",
                "content": """WEBVTT

00:00:01.000 --> 00:00:03.000 position:10% align:left size:35%
Where did he go?
""",
                "expected_lines": 1,
                "first_settings": "position:10% align:left size:35%"
            }
        ]
        
        for case in test_cases:
            with self.subTest(test_name=case["test_name"]):
                log_test_name(f'VttFileHandler parsing - {case["test_name"]}')
        
                data = self.handler.parse_string(case["content"])
                lines = data.lines
                
                self.assertLoggedEqual(f"{case['test_name']}_line_count", case['expected_lines'], len(lines))
                
                if case.get("check_format"):
                    self.assertLoggedEqual(f"{case['test_name']}_format", '.vtt', data.detected_format)
                
                if case["expected_lines"] > 0:
                    if "first_start" in case:
                        self.assertLoggedEqual(case['first_start'], case['first_start'], lines[0].start)
                    
                    if "first_text" in case:
                        self.assertLoggedEqual(case['first_text'], case['first_text'], lines[0].text)
                    
                    if "first_cue_id" in case:
                        cue_id = lines[0].metadata.get('cue_id')
                        self.assertLoggedEqual(case['first_cue_id'], case['first_cue_id'], cue_id)
                    
                    if "first_settings" in case:
                        settings = lines[0].metadata.get('vtt_settings')
                        self.assertLoggedEqual(case['first_settings'], case['first_settings'], settings)
                
                if case["expected_lines"] > 1:
                    if "second_text" in case:
                        self.assertLoggedEqual(case['second_text'], case['second_text'], lines[1].text)
                    
                    if case.get("second_no_cue_id"):
                        has_no_cue_id = 'cue_id' not in lines[1].metadata
                        self.assertLoggedTrue(f"{case['test_name']}_second_line_has_no_cue_id", has_no_cue_id)

    def test_note_block_without_inline_text(self):
        """Ensure NOTE blocks starting with just 'NOTE' are preserved."""

        vtt_content = """WEBVTT

NOTE
This is a note
spanning lines

00:00:00.000 --> 00:00:01.000
Subtitle
"""

        data = self.handler.parse_string(vtt_content)
        notes = data.metadata.get('vtt_notes', [])
        self.assertLoggedEqual('Note count', 1, len(notes))
        self.assertLoggedIn('Note contains text', 'This is a note', notes[0])
    
    def test_cue_settings_preservation(self):
        """Test that cue settings are preserved in metadata."""
        
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
        self.assertLoggedEqual('First cue settings', 'position:10%,line-left align:left size:35%', first_settings)
        
        # Check second cue settings
        second_settings = lines[1].metadata.get('vtt_settings', '')
        self.assertLoggedEqual('Second cue settings', 'position:90% align:right size:35%', second_settings)
        
        # Test round-trip preservation
        composed = self.handler.compose(data)
        round_trip_data = self.handler.parse_string(composed)
        round_trip_lines = round_trip_data.lines
        
        self.assertLoggedEqual("Round-trip settings preserved", first_settings, round_trip_lines[0].metadata.get('vtt_settings'))
        self.assertEqual(round_trip_lines[1].metadata.get('vtt_settings'), second_settings)
    
    def test_style_blocks_preservation(self):
        """Test that STYLE blocks are preserved in file metadata."""
        
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
        self.assertLoggedEqual('Number of style blocks', 2, len(vtt_styles))
        
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
        self.assertLoggedEqual('Round-trip styles preserved', 2, len(rt_styles))
        
        # Check content is preserved
        self.assertLoggedIn('Style content preserved', 'papayawhip', rt_styles[0])
        self.assertIn("peachpuff", rt_styles[1])
    
    def test_speaker_voice_tags(self):
        """Test that speaker voice tags are handled correctly."""
        
        vtt_with_speakers = """WEBVTT

00:00:00.000 --> 00:00:02.000
<v.first.loud Esme>It's a blue apple tree!</v>

00:00:02.000 --> 00:00:04.000
<v Mary>No way!</v>

00:00:04.000 --> 00:00:06.000
<v Esme>Hee!</v> <i>laughter</i>

00:00:06.000 --> 00:00:08.000
<v.loud Mary>That's awesome!</v>
"""
        
        data = self.handler.parse_string(vtt_with_speakers)
        lines = data.lines
        
        self.assertEqual(len(lines), 4)
        
        # Check speaker extraction - partial voice tags are ignored
        speakers = [line.metadata.get('speaker') for line in lines]
        expected_speakers = ['Esme', 'Mary', None, 'Mary']
        self.assertLoggedEqual('Extracted speakers', expected_speakers, speakers)
        
        # Check text processing (full-line voice tags removed, partial tags left)
        texts = [line.text for line in lines]
        expected_texts = [
            "It's a blue apple tree!",
            "No way!",
            "<v Esme>Hee!</v> <i>laughter</i>",
            "That's awesome!"
        ]
        self.assertLoggedEqual('Processed texts', expected_texts, texts)
        
        # Test round-trip (voice tags restored)
        composed = self.handler.compose(data)
        self.assertLoggedIn('Voice tags restored', '<v Esme>', composed)
        self.assertIn("<v Mary>", composed)
        
        # Verify round-trip parsing
        round_trip_data = self.handler.parse_string(composed)
        rt_speakers = [line.metadata.get('speaker') for line in round_trip_data.lines]
        self.assertLoggedEqual('Round-trip speakers', expected_speakers, rt_speakers)
    
    voice_tag_cases = {
        "<v Mary>Hello world</v>": "Hello world",
        "<v.class>Test text</v>": "Test text", 
        "<v.first-second Mary>Hyphenated class</v>": "Hyphenated class",
        "<v.multi-word-class John>Multiple hyphens</v>": "Multiple hyphens",
        "<v.under_score-mixed>Mixed separators</v>": "Mixed separators",
        "<v>No attributes</v>": "No attributes",
        "<v.class1.class2>Multiple classes</v>": "Multiple classes",
        "Text <v Speaker>with voice</v> inside": "Text <v Speaker>with voice</v> inside",
        "<v.loud Mary>Start</v> and <v John>end</v>": "<v.loud Mary>Start</v> and <v John>end</v>"
    }
    
    def test_voice_tag_stripping(self):
        """Test that all voice tag variations are completely stripped."""
        
        for vtt_text, expected_clean in self.voice_tag_cases.items():
            with self.subTest(vtt_text=vtt_text):
                result_text, _ = self.handler._process_vtt_text(vtt_text)
                self.assertLoggedEqual(vtt_text, expected_clean, result_text)
    
    voice_metadata_cases = {
        "<v Mary>Hello</v>": {"speaker": "Mary"},
        "<v.class>Test</v>": {"voice_classes": ["class"]},
        "<v.first-second Mary>Text</v>": {"voice_classes": ["first-second"], "speaker": "Mary"},
        "<v.class1.class2 John>Multiple</v>": {"voice_classes": ["class1", "class2"], "speaker": "John"},
        "<v>No attrs</v>": {},
        "<v.loud>Class only</v>": {"voice_classes": ["loud"]},
        "<v Speaker>Name only</v>": {"speaker": "Speaker"},
        "Text <v Speaker>partial</v> inside": {}
    }
    
    def test_voice_tag_metadata_extraction(self):
        """Test that voice tag metadata is correctly extracted."""
        
        for vtt_text, expected_metadata in self.voice_metadata_cases.items():
            with self.subTest(vtt_text=vtt_text):
                _, result = self.handler._process_vtt_text(vtt_text)
                self.assertLoggedEqual(vtt_text, expected_metadata, result)
    
    def test_voice_tag_round_trip(self):
        """Test that voice tags are preserved through parse/compose cycle."""
        
        test_vtt = """WEBVTT

00:00:01.000 --> 00:00:02.000
<v.first-second Mary>Hyphenated class text</v>

00:00:02.000 --> 00:00:03.000
<v.class1.class2 John>Multiple classes</v>

00:00:03.000 --> 00:00:04.000
<v Speaker>Simple speaker</v>
"""
        
        # Parse the VTT
        data = self.handler.parse_string(test_vtt)
        lines = data.lines
        
        # Verify clean text extraction
        clean_texts = [line.text for line in lines]
        expected_clean = ["Hyphenated class text", "Multiple classes", "Simple speaker"]
        self.assertLoggedEqual('Clean texts', expected_clean, clean_texts)
        
        # Compose back to VTT
        composed = self.handler.compose(data)
        
        # Verify tags are restored (no duplication)
        self.assertLoggedNotIn('No tag duplication', '<v.first-second Mary><v.first-second Mary>', composed)
        self.assertNotIn("</v></v>", composed)
        
        # Parse again to verify metadata preservation
        round_trip_data = self.handler.parse_string(composed)
        rt_lines = round_trip_data.lines
        
        # Check metadata preservation
        first_metadata = rt_lines[0].metadata
        expected_first = {"voice_classes": ["first-second"], "speaker": "Mary"}
        self.assertLoggedEqual('Round-trip metadata', expected_first, {k: v for k, v in first_metadata.items() if k in ['voice_classes', 'speaker']})
        self.assertEqual(first_metadata.get("speaker"), "Mary")

if __name__ == '__main__':
    unittest.main()
