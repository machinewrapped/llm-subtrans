# Multi-Format Subtitle Support Implementation Proposal

## Executive Summary

This document proposes a comprehensive implementation plan to extend LLM-Subtrans with support for multiple subtitle file formats while maintaining the existing SRT functionality and internal architecture. The system will use a format-agnostic approach with pluggable file handlers that auto-register based on file extensions.

## Current State Analysis

### Existing Architecture
- **Core Internal Representation**: `SubtitleLine` objects with timing, text, and metadata
- **File Format Handling**: Currently hardcoded to SRT via `SrtFileHandler`
- **Integration Points**: `Subtitles.py:63` hardcodes `SrtFileHandler()` instantiation
- **Serialization**: `SubtitleSerialisation.py` handles project file persistence
- **Interface**: Abstract `SubtitleFileHandler` already exists with proper methods

### Current Limitations
- Only SRT format supported
- File format hardcoded in `Subtitles` class
- No format detection mechanism
- No extensibility for new formats

## Proposed Architecture

### Responsibility Separation
**SubtitleProject** becomes responsible for:
- Format detection and handler selection via `SubtitleFormatRegistry`
- Managing format preferences (input format vs output format)
- Orchestrating format conversions by creating new `Subtitles` instances
- Coordinating file I/O operations with appropriate handlers

**Subtitles** becomes format-agnostic by:
- Requiring a `file_handler` parameter during construction
- Focusing purely on subtitle data management and business logic
- No format-specific code or assumptions

**Format Conversion Flow**:
```python
try:
  new_handler = SubtitleFormatRegistry.get_handler_by_format(target_format)
  converted_subtitles = new_handler.convert_from(self.subtitles)
  self.subtitles = converted_subtitles
except Exception as e:
  logging.error(...)
```

### Format Detection & Routing System
A new `SubtitleFormatRegistry` will:
- Auto-discover handlers in `PySubtitle/Formats/` directory
- Map file extensions to appropriate handlers
- Provide fallback mechanisms for unknown formats
- Support format detection by file content when extension is ambiguous

### Handler Auto-Discovery
- All handler classes in `PySubtitle/Formats/*.py` that inherit from `SubtitleFileHandler` will be automatically registered
- Registration based on `get_file_extensions()` return values
- Handlers can override each other based on priority system
- Runtime registration for dynamic handler loading

### Core Use Case Focus
The implementation prioritizes **subtitle translation** over format conversion:
- Primary workflow: Load subtitles → Translate → Save (same format)
- Being able to save as a different format is a secondary benefit

## Implementation Plan

### Phase 1: Format Registry Foundation
**Requirements**:
- Create `SubtitleFormatRegistry` class
- Implement auto-discovery mechanism for handlers
- Add format detection by file extension
- Create unit tests for registry functionality

**Acceptance Tests**:
- [ ] Registry discovers existing `SrtFileHandler` automatically
- [ ] Registry maps `.srt` extension to `SrtFileHandler`
- [ ] Registry raises appropriate errors for unknown extensions
- [ ] Registry can enumerate all available formats
- [ ] Registry handles duplicate extension registration with priority

**Files to Modify**:
- Create: `PySubtitle/SubtitleFormatRegistry.py`
- Create: `PySubtitle/UnitTests/test_SubtitleFormatRegistry.py`

### Phase 2: Integration with SubtitleProject and Subtitles
**Requirements**:
- Modify `Subtitles.__init__()` to require `file_handler` parameter
- Update `SubtitleProject` to handle format detection and handler selection
- Implement format conversion logic in `SubtitleProject`
- Maintain backward compatibility through `SubtitleProject`
- Add support for explicitly specifying input/output formats

**Acceptance Tests**:
- [ ] Existing SRT files continue to load without changes via `SubtitleProject`
- [ ] `SubtitleProject` detects format automatically by file extension
- [ ] Format can be explicitly specified via `SubtitleProject` parameters
- [ ] Format conversion creates new `Subtitles` instance with different handler
- [ ] `Subtitles` constructor requires `file_handler` parameter
- [ ] All existing unit tests continue to pass

**Files to Modify**:
- `PySubtitle/Subtitles.py`: Require `file_handler` parameter, remove hardcoded SRT handler
- `PySubtitle/SubtitleProject.py`: Add format detection, handler selection, conversion logic

### Phase 3: ASS/SSA Format Support
**Requirements**:
- Implement `AssFileHandler` class supporting Advanced SubStation Alpha format
- Handle ASS-specific features: styles, positioning, effects, colors
- Store ASS-specific data in `SubtitleLine.metadata`
- Support both reading and writing ASS format
- Maintain index uniqueness for dialogue events

**Acceptance Tests**:
- [ ] Parse basic ASS files with dialogue events
- [ ] Preserve style information in metadata
- [ ] Handle multi-line dialogue correctly
- [ ] Export to ASS format maintaining original styling
- [ ] Assign unique indices to all dialogue events
- [ ] Handle ASS timing format conversion
- [ ] Support V4+ Styles and V4 Styles sections

**Files to Create**:
- `PySubtitle/Formats/AssFileHandler.py`
- `PySubtitle/UnitTests/test_AssFileHandler.py`

**ASS-Specific Implementation Details**:
- Parse `[Script Info]`, `[V4+ Styles]`, `[Events]` sections
- Store style definitions in metadata
- Convert ASS time format (0:00:00.00) to timedelta
- Handle dialogue event fields: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
- Preserve advanced features like override codes in metadata
- Generate unique indices for events that may not have them natively
- Consider suitability of `pysubs2` library for parsing and conversion

### Phase 4: Format conversion
**Requirements**
- Format conversion is handled by SubtitleProject delegating to `SrtFileHandler` or `AssFileHandler`
- Source and destination formats auto-detected based on file extensions

**Acceptance Tests**
- [ ] Load .ass subtitle file and save as .srt without errors
- [ ] Load .srt subtitle file and save as .ass without errors
- [ ] Load converted files as new SubtitleProject without errors

### Phase 5: Caption Format Support (Transcription-Focused)
**Requirements**:
- Implement `VttFileHandler` for WebVTT (common web format)
- Implement `SccFileHandler` for SCC (broadcast standard for CEA-608/708)
- Implement `TtmlFileHandler` for TTML (advanced XML-based format)
- Focus on formats commonly output by transcription services
- Support speaker diarization metadata preservation from Whisper+PyAnnote workflows

**Priority Format Rationale**:
- **WebVTT**: Universal web standard, supported by all major platforms
- **SCC**: US broadcast standard, required by YouTube/Netflix for professional content
- **TTML**: Advanced format supporting complex styling, used by streaming services
- **CEA-608/708 support**: Via SCC format for broadcast compliance

**Acceptance Tests**:
- [ ] Parse WebVTT files with WEBVTT header and cue settings
- [ ] Parse SCC files preserving CEA-608/708 caption styling and positioning
- [ ] Parse TTML files with XML structure and advanced styling
- [ ] Preserve speaker identification metadata from transcription workflows
- [ ] Export to each format maintaining compliance with respective standards
- [ ] Handle timestamp format conversions between formats
- [ ] Support transcription service output formats (OpenAI Whisper, Gemini)

**Files to Create**:
- `PySubtitle/Formats/VttFileHandler.py`
- `PySubtitle/Formats/SccFileHandler.py`  
- `PySubtitle/Formats/TtmlFileHandler.py`
- `PySubtitle/UnitTests/test_VttFileHandler.py`
- `PySubtitle/UnitTests/test_SccFileHandler.py`
- `PySubtitle/UnitTests/test_TtmlFileHandler.py`

### Phase 6: Enhanced Format Detection
**Requirements**:
- Request sample files from the user for testing format detection
- Add content-based format detection for ambiguous cases
- Delegate detection to registered `SubtitleFileHandler` classes for plug-and-play extensibility
- Support format detection when file extension is missing/incorrect
- Improve error reporting for format detection failures

**Acceptance Tests**:
- [ ] Detect SRT format by content structure when extension missing
- [ ] Detect ASS format by `[Script Info]` section
- [ ] Detect WebVTT format by `WEBVTT` header
- [ ] Provide clear error messages for undetectable formats
- [ ] Handle edge cases with malformed files gracefully

**Files to Modify**:
- `PySubtitle/SubtitleFormatRegistry.py`: Add content detection hooks
- `PySubtitle/SubtitleFileHandler.py`: Add detection method to be implemented in subclasses

### Phase 7: Serialization Support
**Requirements**:
- Extend `SubtitleSerialisation.py` to preserve format information in project files (if necessary)
- Store original file format in project metadata
- Support format conversion during project operations

**Acceptance Tests**:
- [ ] Project files store original subtitle format
- [ ] Reloading project maintains correct format handler
- [ ] Format can be changed for output independently of input
- [ ] Serialization preserves format-specific metadata
- [ ] Legacy project files continue to work (assume SRT)

**Files to Modify**:
- `PySubtitle/SubtitleSerialisation.py`: Add format preservation (if required)
- `PySubtitle/Subtitles.py`: Store format information
- `PySubtitle/SubtitleProject.py`: Handle format in project operations

### Phase 8: GUI Integration
**Requirements**:
- Update file filters to show all supported formats
- Display format information in project settings
- Add format-specific options to `SettingsDialog`, extensible by registered handlers

**Acceptance Tests**:
- [ ] File open dialog shows all supported formats
- [ ] File save dialog shows all supported formats
- [ ] Project settings display current format
- [ ] Format-specific options appear in settings
- [ ] Format conversion preserves data integrity
- [ ] Error handling for unsupported format operations

**Files to Modify**:
- GUI file dialog components
- Settings dialog for format-specific options
- Project view to show format information

### Phase 9: Documentation and CLI Updates
**Requirements**:
- Update CLI to support format specification
- Add format listing command
- Update documentation with supported formats
- Create format-specific usage examples
- Update help text and error messages

**Acceptance Tests**:
- [ ] CLI accepts format parameter (e.g., `--format ass`)
- [ ] CLI can list supported formats (e.g., `--list-formats`)
- [ ] Help documentation includes format information
- [ ] Error messages specify available formats
- [ ] Examples provided for each supported format

**Files to Modify**:
- CLI argument parsing
- Help text and documentation
- Example files for each format

## Technical Specifications

### SubtitleFormatRegistry API
```python
class SubtitleFormatRegistry:
    @staticmethod
    def get_handler(filepath: str, format_hint: str|None = None) -> SubtitleFileHandler
    
    @staticmethod
    def get_handler_by_format(format_name: str) -> SubtitleFileHandler
    
    @staticmethod
    def detect_format_from_extension(filepath: str) -> str
    
    @staticmethod
    def detect_format_from_content(content: str) -> str
    
    @staticmethod
    def list_supported_formats() -> dict[str, list[str]]
    
    @staticmethod
    def register_handler(handler_class: type[SubtitleFileHandler]) -> None
```

### Extended SubtitleLine Metadata Schema
```python
# ASS Format Metadata
{
    "format": "ass",
    "style": "Default",
    "layer": 0,
    "margin_l": 0,
    "margin_r": 0,
    "margin_v": 0,
    "effect": "",
    "override_codes": "{\\i1}italic text{\\i0}"
}

# WebVTT Format Metadata
{
    "format": "vtt",
    "cue_id": "subtitle-001",
    "settings": "align:center position:50%",
    "styling": "<c.class>colored text</c>"
}
```

### File Handler Requirements
All format handlers must:
1. Inherit from `SubtitleFileHandler`
2. Implement all abstract methods
3. Return unique indices for all subtitle lines
4. Store format-specific data in `SubtitleLine.metadata`
5. Handle format conversion gracefully
6. Include comprehensive error handling
7. Support both file and string input/output

### Unique Index Assignment Strategy
For formats that don't have native indices (like ASS):
- Sequential numbering starting from 1
- Preserve original event order
- Handle missing/duplicate indices by reassignment
- Maintain consistency across parse/compose cycles

## Risk Assessment

### High Risk
- **Breaking Changes**: Modifications to core `Subtitles` class could break existing functionality
  - **Mitigation**: Comprehensive regression testing, backward compatibility preservation
- **Performance Impact**: Format detection could slow file loading
  - **Mitigation**: Efficient detection algorithms, caching mechanisms

### Medium Risk
- **Format Complexity**: ASS format has many advanced features that could be difficult to implement
  - **Mitigation**: Phased implementation, focus on common use cases first
- **Metadata Loss**: Converting between formats could lose format-specific information
  - **Mitigation**: Comprehensive metadata preservation, format-specific warnings

### Low Risk
- **Registry Discovery**: Auto-discovery mechanism could fail to find handlers
  - **Mitigation**: Explicit registration fallback, detailed error messages

## Testing Strategy

### Unit Tests
- Format registry functionality
- Each file handler implementation
- Format detection algorithms
- Metadata preservation
- Error handling scenarios

### Integration Tests
- End-to-end file loading/saving
- GUI format selection
- CLI format specification
- Project file format preservation

### Regression Tests
- All existing SRT functionality
- Project file compatibility
- API compatibility

### Manual Tests
- Real-world subtitle files
- Format conversion accuracy
- GUI usability
- Performance benchmarking

## Dependencies

### Required Libraries
- **ASS Support**: Consider `pysubs2` or implement native parser
- **WebVTT Support**: `webvtt-py` library or native implementation
- **Format Detection**: Use existing Python libraries for content analysis

### License Compatibility
All selected libraries must be:
- MIT, BSD, or similarly permissive licenses
- Compatible with existing project license
- Actively maintained

## Migration Path

### For Users
1. Existing SRT files continue to work without changes
2. New formats available through same interface
3. Project files automatically migrate format information
4. GUI provides intuitive format selection

### For Developers
1. Existing `SubtitleFileHandler` interface maintained and extended
2. New handlers follow established patterns
3. Format registry provides central management
4. Comprehensive documentation for adding new formats

## Success Metrics

- [ ] All existing functionality preserved
- [ ] At least 3 additional formats supported (ASS, WebVTT, SCC)
- [ ] Zero breaking changes to public API
- [ ] 100% test coverage for new components
- [ ] User acceptance

## Future Extensions: Transcription + Translation Workflow

### Audio Transcription Integration
**Vision**: Extend LLM-Subtrans to support audio-to-subtitle-to-translation workflows, leveraging the format-agnostic architecture to handle diverse transcription outputs.

#### Phase A: OpenAI Whisper Integration
- Add audio file support (mp3, mp4, wav, webm, m4a)
- Integrate OpenAI Whisper API or local Whisper models
- Support timestamp-accurate transcription output
- Handle multiple languages with automatic detection

#### Phase B: Speaker Diarization Support
- Integrate WhisperX or Whisper+PyAnnote for speaker identification
- Store speaker information in `SubtitleLine.metadata`
- Support multi-speaker subtitle generation
- Enable speaker-based translation customization

#### Phase C: Advanced Transcription Features
- **Gemini Audio Processing**: Support for Google Gemini's multimodal audio transcription
- **Batch Audio Processing**: Process multiple audio files with consistent speaker identification

### Format-Specific Transcription Outputs
The multi-format architecture naturally supports transcription service outputs:
- **Whisper → SRT/VTT**: Standard timestamped transcription
- **Diarized Output → ASS**: Speaker-based styling and positioning  
- **Broadcast Content → SCC**: CEA-608/708 compliant captions
- **Streaming Services → TTML**: Advanced styling for platform requirements

### Enhanced Metadata Schema for Transcription
```python
# Speaker Diarization Metadata
{
    "transcription_source": "whisper_diarized",
    "speaker_id": "SPEAKER_00",
    "confidence_score": 0.95,
    "audio_segment": {"start": 12.34, "end": 18.67},
    "language_detected": "en",
}
```

### Integration Benefits
- **Single Tool Workflow**: Audio → Transcription → Translation → Formatted Output
- **Format Flexibility**: Choose optimal format for target platform (broadcast, web, mobile)
- **Speaker Context**: Leverage speaker information for more accurate translation
- **Quality Control**: Maintain transcription metadata for review and correction

### Additional Format Support (Lower Priority)
- YouTube SBV (simple timestamped format)
- MicroDVD (SUB) (frame-based timing)
- SAMI (SMI) (Microsoft legacy format)
- EBU-STL (European broadcast standard)

### Advanced Features
- **Format-specific editing**: Maintain format integrity during translation
- **Quality validation**: Format compliance checking and repair

## Conclusion

This proposal provides a comprehensive roadmap for implementing multi-format subtitle support in LLM-Subtrans. The phased approach minimizes risk while ensuring backward compatibility and extensibility. The format-agnostic architecture will enable easy addition of new formats in the future while maintaining the clean separation between business logic and file I/O operations.

The implementation leverages the existing `SubtitleFileHandler` interface and builds upon the solid foundation already established in the codebase. By following this plan, LLM-Subtrans will become a more versatile and powerful subtitle translation tool capable of handling the diverse subtitle formats used across different platforms and applications.