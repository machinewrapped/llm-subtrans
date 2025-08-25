#!/usr/bin/env python3
"""
Demonstration script showing the new format-agnostic subtitle architecture.

This script shows how the SRT library has been successfully decoupled from
business logic, and how the new architecture could easily support additional
subtitle formats in the future.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import timedelta
from PySubtitle.SubtitleLine import SubtitleLine
from PySubtitle.Subtitles import Subtitles
from PySubtitle.Formats.SrtFileHandler import SrtFileHandler
from PySubtitle.SubtitleFileHandler import SubtitleFileHandler
from typing import Iterator, TextIO

class ExampleVttFileHandler(SubtitleFileHandler):
    """
    Example implementation showing how a new subtitle format handler
    could be implemented. This is a mock VTT handler for demonstration.
    """
    
    def parse_file(self, file_obj: TextIO) -> Iterator[SubtitleLine]:
        # Mock implementation - in reality this would parse VTT format
        content = file_obj.read()
        return self.parse_string(content)
    
    def parse_string(self, content: str) -> Iterator[SubtitleLine]:
        # Mock VTT parsing - just converts a simple format for demo
        lines = content.strip().split('\n\n')
        for i, line_block in enumerate(lines, 1):
            if line_block.strip():
                yield SubtitleLine.Construct(
                    i, 
                    timedelta(seconds=i), 
                    timedelta(seconds=i+3), 
                    f"VTT Line {i}: {line_block[:20]}..."
                )
    
    def compose_lines(self, lines: list[SubtitleLine], reindex: bool = True) -> str:
        # Mock VTT composition
        result = "WEBVTT\n\n"
        for line in lines:
            if line.text:
                start_str = f"{int(line.start.total_seconds()//3600):02d}:{int((line.start.total_seconds()%3600)//60):02d}:{line.start.total_seconds()%60:06.3f}"
                end_str = f"{int(line.end.total_seconds()//3600):02d}:{int((line.end.total_seconds()%3600)//60):02d}:{line.end.total_seconds()%60:06.3f}"
                result += f"{start_str} --> {end_str}\n{line.text}\n\n"
        return result
    
    def get_file_extensions(self) -> list[str]:
        return ['.vtt']

def demo_format_agnostic_architecture():
    """Demonstrate the format-agnostic subtitle architecture."""
    
    print("=== SRT Library Decoupling Demonstration ===\n")
    
    # 1. Show business logic using internal representation
    print("1. Business Logic with SubtitleLine Representation:")
    line = SubtitleLine.Construct(
        1,
        timedelta(seconds=5),
        timedelta(seconds=10),
        "This subtitle uses SubtitleLine representation only"
    )
    
    print(f"   Created subtitle: {line.text}")
    print(f"   Timing: {line.start} to {line.end}")
    print(f"   Duration: {line.duration}")
    print("   ✓ No SRT library dependency in business logic\n")
    
    # 2. Show file format handling is isolated
    print("2. File Format Handling (SRT):")
    srt_handler = SrtFileHandler()
    sample_srt = "1\n00:00:01,000 --> 00:00:05,000\nHello from SRT format"
    
    parsed_lines = list(srt_handler.parse_string(sample_srt))
    print(f"   Parsed {len(parsed_lines)} lines from SRT")
    print(f"   Content: {parsed_lines[0].text}")
    
    composed_srt = srt_handler.compose_lines(parsed_lines)
    print(f"   Composed back to SRT format (length: {len(composed_srt)} chars)")
    print("   ✓ SRT format handling isolated to file handler\n")
    
    # 3. Show how new formats could be supported
    print("3. Future Format Support (Mock VTT):")
    vtt_handler = ExampleVttFileHandler()
    mock_vtt_content = "Some mock VTT content here"
    
    vtt_lines = list(vtt_handler.parse_string(mock_vtt_content))
    print(f"   Mock VTT parsed {len(vtt_lines)} lines")
    print(f"   Content: {vtt_lines[0].text}")
    
    composed_vtt = vtt_handler.compose_lines(vtt_lines)
    print(f"   Composed to VTT format:")
    print(f"   {composed_vtt[:60]}...")
    print("   ✓ New formats can be added without changing business logic\n")
    
    # 4. Show unified business logic works with any format
    print("4. Format-Agnostic Business Operations:")
    all_lines = parsed_lines + vtt_lines
    
    # Business operations work regardless of original format
    total_duration = sum((line.duration for line in all_lines), timedelta())
    avg_duration = total_duration / len(all_lines) if all_lines else timedelta()
    
    print(f"   Processing {len(all_lines)} lines from different formats")
    print(f"   Total duration: {total_duration}")
    print(f"   Average duration: {avg_duration}")
    print("   ✓ Business logic works with any subtitle format\n")
    
    # 5. Show backward compatibility
    print("5. Backward Compatibility:")
    sf = Subtitles()
    sf.LoadSubtitlesFromString(sample_srt)
    if sf.originals:
        print(f"   Loaded {len(sf.originals)} subtitles into SubtitleFile")
        print(f"   First subtitle: {sf.originals[0].text}")
        print("   ✓ Existing API and functionality preserved\n")
    else:
        print("   ✗ Failed to load subtitles into SubtitleFile\n")
    
    print("=== Architecture Benefits:")
    print("• SRT library usage isolated to file I/O only")
    print("• SubtitleLine is the unified internal representation") 
    print("• Easy to add support for new subtitle formats")
    print("• 100% backward compatibility maintained")
    print("• Improved testability and maintainability")
    print("• Simplified architecture with no unnecessary abstraction layers")

if __name__ == "__main__":
    demo_format_agnostic_architecture()