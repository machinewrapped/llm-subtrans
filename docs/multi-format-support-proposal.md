# Multi-Format Subtitle Support Implementation Proposal

**Note** tests MUST be invoked via `python tests/unit_tests.py` to bootstrap the test environment.

## Executive Summary

This document captures the architecture and decisions behind LLM-Subtrans's multi-format subtitle support through Phase 7 and outlines the remaining work. The system now uses a format-agnostic approach with pluggable file handlers that auto-register based on file extensions.

## Architecture Overview

- **Core Internal Representation**: `SubtitleLine` objects with timing, text, and metadata
- **File Format Handling**: `SubtitleFormatRegistry` discovers handlers such as `SrtFileHandler` and `SSAFileHandler`
- **Integration Points**: `SubtitleProject` reads and writes `Subtitles` files by extension
- **Serialization**: `SubtitleSerialisation.py` handles project file persistence
- **Interface**: Abstract `SubtitleFileHandler` defines parsing and composing operations

### Responsibility Separation
**SubtitleProject** becomes responsible for:
- Format detection and handler selection via `SubtitleFormatRegistry`

**Subtitles** becomes format-agnostic by:
- Determining the appropriate `file_handler` to use based on filename
- Focusing purely on subtitle data management and business logic
- No format-specific code or assumptions

### Format Detection & Routing System
The `SubtitleFormatRegistry`:
- Handler classes in `PySubtitle/Formats/*.py` that inherit from `SubtitleFileHandler` are automatically registered
- Registration is driven by each handler's `SUPPORTED_EXTENSIONS` class variable
- Maps file extensions to appropriate handlers using priority values
- Can auto-detect format based on content
- Supports disabling auto-discovery for controlled test environments

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
 - [x] All existing unit tests continue to pass
 - [x] Project files instantiate appropriate file handler when loading project

**Files to Modify**:
- `PySubtitle/Subtitles.py`: Require `file_handler` parameter, remove hardcoded SRT handler
- `PySubtitle/SubtitleProject.py`: Add format detection, handler selection, conversion logic

### Phase 3: SSA/ASS Format Support [X] COMPLETED
**Requirements**:
- [X] Implement `SSAFileHandler` class supporting Advanced SubStation Alpha format
- [X] Handle SSA-specific features: styles, positioning, effects, colors
- [X] Store SSA-specific data in `SubtitleLine.metadata`
- [X] Support both reading and writing SSA format
- [X] Maintain index uniqueness for dialogue events

**Priority System Implementation**:
- [x] Implemented data-driven `SUPPORTED_EXTENSIONS` class variable architecture
- [x] Priority convention established: 10 (specialist) > 5 (secondary) > 0 (fallback)
- [x] Base class methods `get_file_extensions()` and `get_extension_priorities()` auto-implement from class data
- [x] Registry supports `disable_autodiscovery()` for precise test control

**Acceptance Tests**:
- [X] Parse basic SSA files with dialogue events
- [X] Preserve style information in metadata
- [X] Handle multi-line dialogue correctly
- [X] Export to SSA format maintaining original styling
- [X] Assign unique indices to all dialogue events
- [X] Handle SSA timing format conversion
- [X] Support V4+ Styles and V4 Styles sections
- [x] `SrtFileHandler` (priority 10) maintains highest priority for .srt files

**Files Created**:
- [X] `PySubtitle/Formats/SSAFileHandler.py` (pysubs2-based implementation)
- [X] `PySubtitle/UnitTests/test_SSAFileHandler.py`

**Implementation Outcome**:
The project standardised on a pysubs2-based `SSAFileHandler`, which provides full metadata preservation and round-trip fidelity. Early custom efforts were discarded in favour of the library-backed approach.

**pysubs2 Library Evaluation**:
After implementation comparison, `pysubs2` was identified as the superior approach for most formats:
- **Battle-tested**: Used by video editing professionals
- **Comprehensive**: Supports SSA, WebVTT, TTML, MicroDVD, MPL2, SAMI, TMP, Whisper formats
- **Perfect fidelity**: Complete metadata preservation with round-trip accuracy
- **Professional quality**: Proper format structure and compliance
- **Future-proof**: Automatic updates as library evolves

### Phase 4: Format conversion
We provide the option to read from one format and write to another as a convenience, but the focus of the application is translation of existing subtitles, format conversion is not a core feature (it is best handled by dedicated tools).

### Conversion process
- Source format is autodetected based on the input filename
- Output format is assumed to be the same, by default, but will be autodetected from the output filename if specified
- Content and metadata are passed through and interpreted by the `SubtitleFileHandler` selected for the output format
- `SubtitleFileHandler` can extend or update metadata if necessary

### CLI Support
The user is already able to specify an output path with `-o` or `--output`, so automatic determination of the file handler to use based on the output path is straightforward.

### GUI Support
Currently the user has no control over the output path for translated subtitles, they are saved in the same directory as the `.subtrans` project file with an auto-generated filename based on the project filename, the target language and the extension of the **source** subtitles. 

We will need to add a "format" field to new project settings to allow the user to specify a different format. It should be a drop-down, whose values are auto-populated from the extensions registered with `SubtitleFormatRegistry`. The default value is be deduced from the sourcepath when subtitles are loaded.

**Requirements**
- Destination format auto-detected from output file extensions
- `SubtitleProject.SaveTranslation` calls appropriate handlers for the output format
- Handlers preserve or translate metadata as needed for the target format, passing through any fields they do not use.
- Update open file filters to show all supported formats + `.subtrans` projects
- Supported formats are determined from the registered handlers in `SubtitleFormatRegistry`

**Acceptance Tests**
- [X] Load .srt file and save as .srt without errors
- [X] Load .ass file and save as .ass without errors
- [X] Load .ass subtitle file and save as .srt without errors
- [X] Load .srt subtitle file and save as .ass without errors
- [X] Load `SubtitleProject` with converted formats without errors
- [X] Load legacy `SubtitleProject` without errors
- [X] Format auto-detection from specified output path via CLI
- [X] File open dialogs show all supported formats + `.subtrans` projects

### Phase 5: Documentation and CLI Updates
**Requirements**:
- Add format listing command to CLI
- Update documentation with supported formats
- Create format-specific usage examples
- Update help text and error messages
- Update architecture.md with details of the SubtitleFormatRegistry and SubtitleFileHandler
- Review architecture.md and readme.md in full to ensure they are current and correct

**Files to Modify**:
- CLI argument parsing (subtrans_common.py)
- Documentation (readme.md, architecture.md)

**Acceptance Tests**:
- [X] CLI can list supported formats (e.g., `--list-formats`)
- [X] Help documentation includes format information
- [X] Error messages specify available formats
- [X] Examples provided for each supported format

**Implementation Outcome**:
Phase 5 adds a `--list-formats` option to all CLI tools, documents supported extensions, and improves error messages with available format hints. The architecture documentation now explains the `SubtitleFormatRegistry` and `SubtitleFileHandler` components, and README examples demonstrate format-specific usage and conversion.

### Phase 6: Enhanced Format Detection

**Requirements**:
- [x] Support format detection when file extension is missing/incorrect
- [x] Report detected_format via `SubtitleData` and automatically update the project output format
- [x] Project format and file extension determined by output_path > detected_format > source_path > default (srt) priority order
- [x] Error reporting for format detection failures

**Acceptance Tests**:
- [x] Detect SRT format with .txt extension
- [x] Detect SSA format with .txt extension
- [x] Detect SSA format with .ass extension
- [x] Provide clear error messages for undetectable formats
- [x] Handle edge cases with malformed files gracefully

**Implementation Notes**:
- Leveraged `pysubs2.fileio.detect_format` for content-based detection.
- `SubtitleData` now carries a `detected_format` field consumed by `Subtitles` to select default output extensions.
- CLI `--output` parameters still override auto-detected paths; GUI defaults can be overridden in `NewProjectSettings`.

**Files to Modify**:
- `PySubtitle/SubtitleFormatRegistry.py`: Add format detection hooks
- `PySubtitle/SubtitleFileHandler.py` and subclasses: Add detection methods if necessary

### Phase 7: WebVTT Format Support
Universal web standard, supported by all major platforms, proof of concept for native handlers

**Requirements**:
- [X] Keep existing `SrtFileHandler` (well-tested, SRT-specialized)
- [X] Maintain `SSAFileHandler` for custom handling of tags and metadata
- [X] Implement `VttFileHandler` for WebVTT (common web format) using native parser
- [X] Support speaker diarization metadata preservation from transcription workflows
- [X] Capture advanced VTT features as pass-through metadata
- [X] Export in VTT format maintaining compliance with WebVTT standards

**Acceptance Tests**:
- [X] Maintain existing SRT parsing with current `srt` module
- [X] Maintain existing SSA/ASS parsing with current `SSAFileHandler`
- [X] Parse WebVTT files with WEBVTT header and cue settings
- [X] Preserve speaker identification metadata from voice tags
- [X] Handle cue settings (position, align, size, line, vertical) as pass-through metadata
- [X] Preserve STYLE blocks in file metadata
- [X] Support cue identifiers and multi-line cues
- [X] Handle UTF-8 BOM in VTT files
- [X] Round-trip preservation of all VTT-specific features
- [X] Test format conversion between SRT, SSA, and VTT formats

**Files Created**:
- [X] `PySubtitle/Formats/VttFileHandler.py` (native implementation)
- [X] `PySubtitle/UnitTests/test_VttFileHandler.py`

**Implementation Outcome**:
After research into WebVTT we chose a **native parser approach** over pysubs2 integration for VTT:

- **Translation Focus**: We are focussed on translation, not format conversion.
- **Metadata Pass-Through**: Advanced features (cue settings, STYLE blocks, voice tags) captured as structured metadata and can be restored as-was in the translation.
- **Avoid Complexity**: pysubs2 conversion to SSA-like format adds complexity when VTT format is already close to internal representation
- **Future-ready**: Speaker metadata ready for transcription workflows

Native `VttFileHandler` successfully demonstrates the "keep it simple" approach while capturing sophisticated WebVTT metadata. The handler supports everything from basic subtitles to broadcast-quality WebVTT with positioning, styling, and speaker identification.

### Phase 8: GUI Integration
**Requirements**:
- Add format-specific settings to a new tab `SettingsDialog`, data-driven and extensible by registered handlers (similar to provider settings)

**Acceptance Tests**:
- [ ] Format-specific settings exposed in SettingsDialog

**Files to Modify**:
- SettingsDialog for format-specific options
- SubtitleFileHandler for format-specific options

## Future Development considerations

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

### Integration Benefits
- **Single Tool Workflow**: Audio → Transcription → Translation → Formatted Output
- **Format Flexibility**: Choose optimal format for target platform (broadcast, web, mobile)
- **Speaker Context**: Leverage speaker information for more accurate translation
- **Quality Control**: Maintain transcription metadata for review and correction

### Additional Format Support (Lower Priority)
- YouTube SBV (simple timestamped format)
- MicroDVD (SUB) (frame-based timing)
- Whisper captions

### Advanced Features
- **Format-specific editing**: Maintain format integrity during translation
- **Quality validation**: Format compliance checking and repair


## Technical Specifications

### SubtitleFormatRegistry API
```python
class SubtitleFormatRegistry:
    @classmethod
    def get_handler_by_extension(cls, extension: str) -> type[SubtitleFileHandler]
    
    @classmethod
    def create_handler(cls, extension: str|None, filename: str|None) -> SubtitleFileHandler
    
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
- **0**: Fallback handlers used when no specialist implementation exists

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
For formats that don't have native indices (like SSA):
- Sequential numbering starting from 1
- Preserve original event order
- Handle missing/duplicate indices by reassignment
- Maintain consistency across parse/compose cycles

## Risk Assessment

### High Risk
- **Breaking Changes**: Modifications to core `Subtitles` class could break existing functionality
  - **Mitigation**: Comprehensive regression testing, backward compatibility preservation
- **Performance Impact**: Format detection could slow file loading
  - **Mitigation**: Measure and respond

### Medium Risk
- **Format Complexity**: SSA format has many advanced features that could be difficult to implement
  - **Mitigation**: Phased implementation, focus on common use cases first
- **Metadata Loss**: Converting between formats could lose format-specific information
  - **Mitigation**: Preserve and convert metadata as much as possible, but format conversion is not a priority focus for the app.

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
  - Provides professional-grade parsing for SSA, SRT, WebVTT, TTML, and more
  - Battle-tested by video editing community
  - Comprehensive metadata preservation with round-trip accuracy
  - Provides support for format detection from content

### License Compatibility
Any libraries used must be:
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
1. New handlers follow established patterns
2. Format registry provides central management

## Success Metrics

- [X] **All existing functionality preserved** (81 unit tests continue to pass)
- [X] **Format Registry implemented** with auto-discovery mechanism
- [X] **SSA format support** completed with both fallback and pysubs2-based implementations  
- [X] **Multi-format path handling** fixed for project files and output generation
- [X] **Zero breaking changes** to public API
- [X] **Comprehensive test coverage** for new components (SSAFileHandler, FormatRegistry)
- [X] Keep existing SRT handling with specialized `srt` module
- [X] At least 3 formats supported (SRT [X], SSA/ASS [X], WebVTT [X])
- [ ] User acceptance validation

## pysubs2 Integration Architecture

All pysubs2-based handlers follow the pattern from `SSAFileHandler` (TODO: extract commonalities into a helper or base class)

- **Format-Specific Handlers**: Maintain separate handler classes for each format to enable format-specific optimizations
- **pysubs2 Foundation**: Leverage pysubs2's robust parsing and composition engines
- **Metadata Pass-Through**: Preserve all format-specific metadata for round-trip fidelity
- **Translation Focus**: Optimize for subtitle translation workflow while maintaining format integrity

### Metadata Strategy
- **Standard Fields**: Common subtitle properties (timing, text, style, layer)
- **Format-Specific**: Preserve format-unique properties in structured metadata
- **Round-Trip Preservation**: Store original pysubs2 object data in `_pysubs2_original`
- **Translation-Friendly**: Basic inline formatting (bold, italic) accessible to translators as SRT/HTML style tags

