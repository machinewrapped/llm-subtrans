# LLM-Subtrans Architecture

~~~mermaid
graph TD
    Scripts[scripts] --> GuiSubtrans[GuiSubtrans]
    Scripts --> PySubtrans[PySubtrans]
    GuiSubtrans --> PySubtrans
~~~

This guide maps the main components, where they live, and how they connect.

## Contents

- [System Overview](#system-overview)
- [Entry Points](#entry-points)
- [Module Structure](#module-structure)
- [Data Organization](#data-organization)
- [Translation Architecture](#translation-architecture)
- [Transcription Pipeline](#transcription-pipeline)
- [Command-Line Architecture](#command-line-architecture)
- [Settings Management](#settings-management)
- [GUI Architecture](#gui-architecture)
- [Extending the System](#extending-the-system)

## System Overview

Supports translating subtitle files and transcribing subtitles from video/audio. The GUI and command-line tools share the `PySubtrans` core, which also ships as a pip package.

**Subtitle translation:** Pluggable format support via `SubtitleFormatRegistry`. `Subtitles` contains `SubtitleLine` data split into Scenes and Batches. `SubtitleTranslator` prepares each batch then sends requests via a `TranslationClient` from the selected `TranslationProvider`.

**Media transcription:** `AudioExtractor` and `AudioChunker` prepare audio for processing. `TranscriptionCoordinator` calls the selected `TranscriptionClient` for each chunk, then `TranscriptionLineBuilder` assembles the returned text and timing information into subtitle lines.

**The GUI** adds project controls and background command execution around the core. Its view model keeps the scene, batch, and line views in sync as commands complete; see [gui-architecture.md](gui-architecture.md).

**Options and settings** are stored in a `SettingsType` dictionary, with project- and provider-specific values layered on to application-wide settings.

## Entry Points

| Script | Purpose |
|--------|---------|
| `scripts/gui-subtrans.py` | Launches the GUI, loads persistent settings, and initializes providers |
| `scripts/llm-subtrans.py` | Translates a subtitle file using the selected provider and model |
| `scripts/transcribe.py` | Transcribes media through the shared transcription coordinator |

## Module Structure

### PySubtrans (Core Engine)

`PySubtrans/` contains subtitle data and project management, translation, transcription, settings, and format handling.

**Key classes:**

- `Subtitles`, `SubtitleScene`, `SubtitleBatch`, `SubtitleLine` - subtitle data and its hierarchy
- `SubtitleProject` - project lifecycle and persistence
- `SubtitleTranslator` - translation orchestration
- `TranslationProvider` - translation service integration
- `SubtitleBuilder` - construction of subtitle structures
- `SubtitleEditor` - subtitle mutations

### Shared Helpers

`PySubtrans/Helpers/` contains reusable utilities. Check here before adding a utility; an existing solution or a natural home for shared functionality may already exist.

- `Text` - general text utilities: whitespace and punctuation normalisation, content comparison, and filename sanitising.
- `Script` - script-aware rules: token joining (`JoinWords` / `NeedsSpace` handle CJK vs Latin spacing), full-width punctuation, and RTL detection.
- `LineBreaks` - break/split sequences and finding the best point to break a long line.
- `Dialog` - dialog markers: splitting dialog onto separate lines, normalising markers, and removing empty rows.
- `FillerWords` - the default filler words and their removal.
- `ResponseText` - xml-like tag extraction from translation responses, and summary cleanup.
- `Time` - `timedelta` parsing and formatting, including SRT timestamps and time span labels.
- `Speech` - how long text takes to say, by script, and where its sentences end.
- `Parse` - key/value pairs, name lists, numeric coercion, and retry-delay/error-message extraction from provider responses.
- `SubtitleHelpers` - operations that need `SubtitleLine`: insert-or-replace by number, merging lines, and merging translations back onto originals.
- `ContextHelpers` - assembles batch context and history for translation prompts.
- `Localization` - the `_()` and `tr()` gettext wrappers plus locale discovery.
- `Languages` - language name and BCP-47 tag resolution via Babel locales.
- `InstructionsHelpers` - loading and saving instruction files from bundled resources or the user config directory.
- `Resources` - config directory and resource path resolution, handling portable and frozen builds.
- `TestCases` / `Tests` - `LoggedTestCase`, `SubtitleTestCase`, the `assertLogged*` assertions, dummy subtitle/provider builders, and `skip_if_debugger_attached`.
- `Color`, `Version`, `__init__` - smaller utilities for colour serialisation, version comparison, input/output path derivation, and enum value naming.

### Subtitle Format Handling

`PySubtrans/Formats/` contains `SubtitleFileHandler` implementations. `SubtitleFormatRegistry` selects a handler by file extension and priority; `SubtitleProject` uses it to load, save, and convert subtitle files.

## Data Organization

`Subtitles` contains `SubtitleScene`s, which group `SubtitleBatch`es, which contain `SubtitleLine`s. Scenes and batches are the units used to organize subtitle files for translation.

`SubtitleBatcher` divides subtitles into scenes and batches. `SubtitleBuilder` constructs subtitle structures. `SubtitleProject` coordinates loading, saving, and project settings. Use `SubtitleEditor` for subtitle mutations so thread-safety and locking are handled consistently.

## Translation Architecture

`SubtitleTranslator` builds context-rich requests for subtitle batches, coordinates provider clients and response parsing, handles retries and post-processing, and emits `TranslationEvents`.

Translation providers live in `PySubtrans/Providers/`; their clients are in `PySubtrans/Providers/Clients/`. `TranslationPrompt` prepares requests, and `TranslationParser` maps responses back to subtitle lines.

For provider registration, model discovery, streaming, and provider-specific settings, see [translation-provider-integration.md](translation-provider-integration.md).

## Transcription Pipeline

Media transcription lives in `PySubtrans/Transcription/`:

- `AudioExtractor` and `AudioChunker` read media audio and plan chunks.
- `TranscriptionProvider` and `TranscriptionClient` provide pluggable speech-to-text backends in `PySubtrans/Transcription/Providers/`.
- `TranscriptionLineBuilder` assembles timed subtitle lines. `TranscriptCutter`, `UtteranceSplitter`, `WordAlignment`, and `LineMerger` support segmentation, timing, and line assembly.
- `TranscriptionCoordinator` plans chunks, calls the selected provider client, applies the resume/abort/failure policy, returns a `TranscriptionOutcome`, and emits progress, audio-progress, and segment events. Expected failures are reported in the outcome.

The CLI at `scripts/transcribe.py` and the GUI's `TranscribeMediaCommand` use the same coordinator. For capture and replay tools used to tune line assembly, see [transcription-tuning.md](transcription-tuning.md). `Provider_QwenLocal` uses a local Torch runtime; see [torch-packaging.md](torch-packaging.md) for packaging details.

## Command-Line Architecture

The translation CLI processes a source file synchronously:

1. Parses command-line arguments.
2. Merges arguments and environment variables into an `Options` instance.
3. Uses `CreateProject` to load subtitles and prepare a `SubtitleTranslator`, optionally reading or writing a project file.
4. Saves the translation and updates the optional project file.

## Settings Management

Settings use a layered system:

- `SettingsType` is a typed settings container with getters such as `get_str`, `get_int`, and `get_bool`.
- `PySubtrans.Options` provides application defaults, loads `settings.json`, imports environment and command-line values, and supports project- and provider-specific settings.

## GUI Architecture

The PySide6 GUI connects **MainWindow** and **GuiInterface** to project actions, a **CommandQueue**, and the active **ProjectDataModel**. **ModelView** presents the project tree, selected content, and project settings. Queued model updates are applied on the GUI thread before Qt views refresh.

See [gui-architecture.md](gui-architecture.md) for the command queue and view-update path. [translation-flow.md](translation-flow.md) has the translation-specific sequence diagrams.

## Extending the System

| To add... | Start in... |
|-----------|-------------|
| A subtitle format | `PySubtrans/Formats/`; implement `SubtitleFileHandler` and register it |
| A translation provider | `PySubtrans/Providers/`; see [translation-provider-integration.md](translation-provider-integration.md) |
| A transcription provider | `PySubtrans/Transcription/Providers/`; implement `TranscriptionProvider` and `TranscriptionClient` |
| A GUI feature | `GuiSubtrans/Widgets/` for views, `GuiSubtrans/Commands/` for operations |
| A setting | `Options` and `SettingsDialog` |
| A background operation | `GuiSubtrans/Commands/`; use the `Command` pattern |

Project data changes should go through `CommandQueue` in the GUI, and subtitle mutations should use `SubtitleEditor`.