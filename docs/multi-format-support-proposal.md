# Multi-Format Subtitle Support Implementation Proposal

**Note** tests MUST be invoked via `python scripts/unit_tests.py` to bootstrap the test environment.

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
- [x] Registry discovers existing `SrtFileHandler` automatically
- [x] Registry maps `.srt` extension to `SrtFileHandler`
- [x] Registry raises appropriate errors for unknown extensions
- [x] Registry can enumerate all available formats
- [x] Registry handles duplicate extension registration with priority

**Files to Modify**:
- Create: `PySubtitle/SubtitleFormatRegistry.py`
- Create: `PySubtitle/UnitTests/test_SubtitleFormatRegistry.py`

### Phase 2: Integration with SubtitleProject and Subtitles
**Requirements**:
- Modify `Subtitles.__init__()` to require `file_handler` parameter
- Update `SubtitleProject` to handle format detection and handler selection
- Implement format conversion logic in `SubtitleProject`
- Maintain backward compatibility through `SubtitleProject`

**Acceptance Tests**:
 - [x] Existing SRT files continue to load without changes via `SubtitleProject`
 - [x] `SubtitleProject` detects format automatically by file extension
 - [x] `Subtitles` constructor requires `file_handler` parameter
 - [x] All existing unit tests continue to pass
 - [x] Project files instantiate appropriate file handler when loading project

**Files to Modify**:
- `PySubtitle/Subtitles.py`: Require `file_handler` parameter, remove hardcoded SRT handler
- `PySubtitle/SubtitleProject.py`: Add format detection, handler selection, conversion logic

### Phase 3: ASS/SSA Format Support [X] COMPLETED
**Requirements**:
- [X] Implement `AssFileHandler` class supporting Advanced SubStation Alpha format
- [X] Handle ASS-specific features: styles, positioning, effects, colors
- [X] Store ASS-specific data in `SubtitleLine.metadata`
- [X] Support both reading and writing ASS format
- [X] Maintain index uniqueness for dialogue events

**Priority System Implementation**:
- [x] Implemented data-driven `SUPPORTED_EXTENSIONS` class variable architecture
- [x] Priority convention established: 10 (specialist) > 5 (secondary) > 0 (fallback)
- [x] Base class methods `get_file_extensions()` and `get_extension_priorities()` auto-implement from class data
- [x] Registry supports `disable_autodiscovery()` for precise test control

**Acceptance Tests**:
- [X] Parse basic ASS files with dialogue events
- [X] Preserve style information in metadata
- [X] Handle multi-line dialogue correctly
- [X] Export to ASS format maintaining original styling
- [X] Assign unique indices to all dialogue events
- [X] Handle ASS timing format conversion
- [X] Support V4+ Styles and V4 Styles sections
- [x] `AssFileHandler` (priority 10) overrides `FallbackAssFileHandler` (priority 0) for .ass/.ssa files
- [x] `SrtFileHandler` (priority 10) maintains highest priority for .srt files

**Files Created**:
- [X] `PySubtitle/Formats/FallbackAssFileHandler.py` (Custom implementation - to be deprecated)
- [X] `PySubtitle/Formats/AssFileHandler.py` (pysubs2-based implementation)
- [X] `PySubtitle/UnitTests/test_AssFileHandler.py`

**Implementation Outcome**:
Two implementations were developed and compared:
1. **FallbackAssFileHandler**: Functional custom implementation (to be deprecated)
2. **AssFileHandler**: Superior pysubs2-based implementation with perfect round-trip fidelity

**pysubs2 Library Evaluation**:
After implementation comparison, `pysubs2` was identified as the superior approach for most formats:
- **Battle-tested**: Used by video editing professionals
- **Comprehensive**: Supports ASS, WebVTT, TTML, MicroDVD, MPL2, SAMI, TMP, Whisper formats
- **Perfect fidelity**: Complete metadata preservation with round-trip accuracy
- **Professional quality**: Proper format structure and compliance
- **Future-proof**: Automatic updates as library evolves

**Format-Specific Strategy**: 
- **SRT**: Keep existing `srt` module (well-tested, SRT-specialized)
- **ASS/WebVTT/TTML**: Use pysubs2 for professional-grade handling
- **Specialized formats**: Evaluate on case-by-case basis

### Phase 4: Format conversion
**Requirements**
- Destination format auto-detected based on file extensions
- Format conversion is handled by SubtitleProject by delegating to a `SubtitleFileHandler`
- Metadata is preserved or converted into an appropriate form for the new format
 
**Acceptance Tests**
- [ ] Format conversion creates new `Subtitles` instance with different handler
- [ ] Load .ass subtitle file and save as .srt without errors
- [ ] Load .srt subtitle file and save as .ass without errors
- [ ] Load converted files as new SubtitleProject without errors

### Phase 5: Additional Format Support
**Requirements**:
- Implement `VttFileHandler` for WebVTT (common web format) using pysubs2
- Implement `TtmlFileHandler` for TTML (advanced XML-based format) using pysubs2
- Keep existing `SrtFileHandler` (well-tested, SRT-specialized)
- Consider `SccFileHandler` for SCC (broadcast standard) if needed
- Support speaker diarization metadata preservation from Whisper+PyAnnote workflows
- Leverage pysubs2's native Whisper format support

**Priority Format Rationale**:
- **WebVTT**: Universal web standard, supported by all major platforms
- **TTML**: Advanced format supporting complex styling, used by streaming services
- **SRT**: Keep existing specialized `srt` module implementation
- **Whisper**: Native support for OpenAI Whisper transcription output
- **SCC**: Evaluate custom implementation if broadcast support needed

**Acceptance Tests**:
- [ ] Parse WebVTT files with WEBVTT header and cue settings using pysubs2
- [ ] Parse TTML files with XML structure and advanced styling using pysubs2
- [ ] Maintain existing SRT parsing with current `srt` module
- [ ] Preserve speaker identification metadata from transcription workflows
- [ ] Export to each format maintaining compliance with respective standards
- [ ] Handle timestamp format conversions between formats
- [ ] Support transcription service output formats (OpenAI Whisper, Gemini)
- [ ] Test format conversion between all supported formats

**Files to Create**:
- `PySubtitle/Formats/VttFileHandler.py` (pysubs2-based)
- `PySubtitle/Formats/TtmlFileHandler.py` (pysubs2-based)
- `PySubtitle/UnitTests/test_VttFileHandler.py`
- `PySubtitle/UnitTests/test_TtmlFileHandler.py`

**Implementation Strategy**:
Follow the proven pattern from `AssFileHandler` (formerly `Pysubs2AssFileHandler`):
- Consistent metadata pass-through approach
- `_pysubs2_original` preservation for perfect round-trips
- Format-specific optimizations within each handler
- Comprehensive error handling with SubtitleParseError translation

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

## Critical Architecture Gap: File-Level Metadata Preservation

### Problem Identified
During Phase 3 implementation, a critical flaw was discovered in the current architecture:

**Issue**: ASS files lose their original styling information when translated because:
1. `parse_file()`/`parse_string()` only extract individual dialogue lines
2. File-level metadata (styles, script info, format sections) is discarded during parsing
3. `compose_lines()` operates in isolation without access to original file context
4. Generated output uses default pysubs2 styles instead of preserving originals

**Root Cause**: The `SubtitleFileHandler` interface is too low-level and doesn't account for formats that have rich file-level metadata (ASS styles, WebVTT headers, TTML namespaces, etc.).

#### File-Level Metadata Storage
Solution: File handlers must capture and preserve complete file context

#### Format-Specific Metadata Examples
```python
# ASS File Metadata
{
    "format": "ass",
    "script_info": {"Title": "Movie", "ScriptType": "v4.00+", ...},
    "styles": {"Default": {...}, "Italics": {...}},
    "original_pysubs2_file": SSAFile  # For perfect round-trip
}

# WebVTT File Metadata  
{
    "format": "vtt", 
    "header": "WEBVTT\nNOTE Generated by...",
    "global_styles": "::cue { color: white; }"
}
```

#### Integration Points
- `Subtitles.LoadSubtitles()`: Should return `SubtitleData` with metadata.
- `Subtitles.SaveTranslation()`: Use `compose()` instead of `compose_lines()` 
- File handlers: Store original file structure for perfect round-trip fidelity

## Technical Specifications

### SubtitleFormatRegistry API
```python
class SubtitleFormatRegistry:
    @classmethod
    def get_handler_by_extension(cls, extension: str) -> type[SubtitleFileHandler]
    
    @classmethod
    def create_handler(cls, extension: str) -> SubtitleFileHandler
    
    @classmethod
    def enumerate_formats(cls) -> list[str]
    
    @classmethod
    def register_handler(cls, handler_class: type[SubtitleFileHandler]) -> None
    
    @classmethod
    def discover(cls) -> None
    
    @classmethod
    def disable_autodiscovery(cls) -> None
    
    @classmethod
    def clear(cls) -> None
    
    # Future API extensions:
    @staticmethod
    def detect_format_from_extension(filepath: str) -> str
    
    @staticmethod
    def detect_format_from_content(content: str) -> str
```

### Data-Driven Handler Architecture

**SUPPORTED_EXTENSIONS Class Variable**:
SubtitleFileHandler uses a declarative approach for defining supported formats and their priorities:

```python
class ExampleFileHandler(SubtitleFileHandler):
    SUPPORTED_EXTENSIONS = {
        '.example': 10,  # High priority (specialist handler)
        '.alt': 5        # Medium priority (secondary support)
    }
    
    # Base class automatically implements:
    # - get_file_extensions() -> list[str] 
    # - get_extension_priorities() -> dict[str, int]
```

**Priority Convention**:
- **10+**: Primary/specialist handlers (e.g., `SrtFileHandler` for `.srt` = 10)
- **1-9**: Generic/multi-format handlers with lower precedence  
- **0**: Fallback handlers (e.g., `FallbackAssFileHandler` = 0)

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
- **pysubs2** (v1.8.0+): Universal subtitle format library (MIT License)
  - Provides professional-grade parsing for ASS, SRT, WebVTT, TTML, and more
  - Battle-tested by video editing community
  - Comprehensive metadata preservation with round-trip accuracy
- **Format Detection**: Use existing Python libraries for content analysis when needed

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

- [X] **All existing functionality preserved** (81 unit tests continue to pass)
- [X] **Format Registry implemented** with auto-discovery mechanism
- [X] **ASS format support** completed with both fallback and pysubs2-based implementations  
- [X] **Multi-format path handling** fixed for project files and output generation
- [X] **Zero breaking changes** to public API
- [X] **Comprehensive test coverage** for new components (AssFileHandler, FormatRegistry)
- [ ] At least 3 additional formats supported (ASS [X], WebVTT, TTML pending)
- [ ] Keep existing SRT handling with specialized `srt` module
- [ ] User acceptance validation

**Current Status**: Phase 1-3 completed successfully. pysubs2 integration strategy validated and ready for Phase 5 implementation.

## pysubs2 Integration Architecture

### Design Philosophy
- **Format-Specific Handlers**: Maintain separate handler classes for each format to enable future format-specific optimizations
- **pysubs2 Foundation**: Leverage pysubs2's robust parsing and composition engines
- **Metadata Pass-Through**: Preserve all format-specific metadata for perfect round-trip fidelity
- **Translation Focus**: Optimize for subtitle translation workflow while maintaining format integrity

### Handler Template Pattern
All pysubs2-based handlers follow this proven pattern from `AssFileHandler`:

```python
class [Format]FileHandler(SubtitleFileHandler):
    def parse_string(self, content: str) -> SubtitleData:
        subs = pysubs2.SSAFile.from_string(content)
        
        lines = []
        for index, line in enumerate(subs, 1):
            lines.append(self._pysubs2_to_subtitle_line(line, index))
        
        # Extract serializable metadata
        metadata = {
            'format': '[format]',
            'info': dict(subs.info),
            'styles': {name: style.as_dict() for name, style in subs.styles.items()}
        }
        
        return SubtitleData(lines=lines, metadata=metadata)
    
    def compose(self, data: SubtitleData) -> str:
        subs = pysubs2.SSAFile()
        
        # Restore file-level metadata
        if 'info' in data.metadata:
            subs.info.update(data.metadata['info'])
        if 'styles' in data.metadata:
            for style_name, style_fields in data.metadata['styles'].items():
                subs.styles[style_name] = pysubs2.SSAStyle(**style_fields)
        
        # Convert lines
        for line in data.lines:
            pysubs2_line = self._subtitle_line_to_pysubs2(line)
            subs.append(pysubs2_line)
        
        return subs.to_string("[format]")
    
    def _pysubs2_to_subtitle_line(self, pysubs2_line, index):
        # Convert with metadata preservation
    
    def _subtitle_line_to_pysubs2(self, line):
        # Restore from preserved metadata or use defaults
```

### Metadata Strategy
- **Standard Fields**: Common subtitle properties (timing, text, style, layer)
- **Format-Specific**: Preserve format-unique properties in structured metadata
- **Round-Trip Preservation**: Store original pysubs2 object data in `_pysubs2_original`
- **Translation-Friendly**: Basic inline formatting (bold, italic) accessible to translators

### Migration Benefits
- **Immediate**: Professional-grade format handling
- **Consistency**: Unified behavior across all formats
- **Reliability**: Battle-tested parsing and error handling
- **Future-Proof**: Automatic support for new formats as pysubs2 evolves
- **Maintainability**: Less custom parsing code to maintain

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