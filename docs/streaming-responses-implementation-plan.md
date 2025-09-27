# Streaming Responses Implementation Plan

## Overview
This document outlines the implementation plan for adding streaming response support to PySubtrans. The goal is to enable real-time updates to the GUI as translation responses are received, improving user experience for long-running translations.

## Architecture Analysis

### Current Flow
1. `SubtitleTranslator.TranslateBatch()` calls `TranslationClient.RequestTranslation()`
2. `RequestTranslation()` calls `_request_translation()` (implemented by subclasses)
3. Complete `Translation` object is returned
4. `ProcessBatchTranslation()` processes the entire response
5. `batch_translated` event is emitted with complete batch

### Target Flow (Streaming)
1. `SubtitleTranslator.TranslateBatch()` calls `TranslationClient.RequestTranslation()` with streaming callback
2. `RequestTranslation()` calls `_request_translation()` with streaming callback
3. `_request_translation()` calls `_get_client_response()` with streaming callback
4. `_get_client_response()` handles streaming API, accumulates deltas, calls callback for complete line groups
5. `batch_updated` event emitted for each complete line group
6. `batch_translated` event emitted when streaming completes

## Implementation Plan

### Phase 1: Core Infrastructure
**Goal**: Extend base classes to support streaming concepts

#### Step 1.1: Extend TranslationEvents
- [x] Add `batch_updated` signal to `TranslationEvents`
- [x] Test: Verify new signal can be created and connected

#### Step 1.2: Extend TranslationClient Base Class
- [x] Add `supports_streaming` property to `TranslationClient`
- [x] Add streaming callback parameter to `RequestTranslation()` and `_request_translation()`
- [x] Update method signatures to support optional streaming callbacks
- [x] Test: Verify base class changes don't break existing functionality

#### Step 1.3: Update SubtitleTranslator
- [x] Add streaming callback handler to `TranslateBatch()`
- [x] Implement partial response processing logic
- [x] Add logic to emit `batch_updated` events for complete line groups
- [x] Ensure validation only occurs on complete responses
- [x] Test: Verify non-streaming translations still work correctly

### Phase 2: OpenAI Streaming Implementation
**Goal**: Implement streaming for OpenAI Reasoning Client

#### Step 2.1: OpenAI Reasoning Client Streaming
- [x] Add streaming support detection to `OpenAIReasoningClient`
- [x] Implement `_get_client_response()` method to handle streaming vs non-streaming
- [x] Add delta accumulation and processing logic to detect complete line groups
- [x] Implement partial translation creation and final response formatting
- [x] Test: Verify streaming requests work with OpenAI API
- [x] Test: Verify fallback to non-streaming for unsupported models

#### Step 2.2: Provider Settings
- [x] Add `stream_responses` setting to `Provider_OpenAI`
- [x] Add GUI option for streaming responses (automatic with Provider GetOptions() method)
- [x] Test: Verify setting can be toggled and persists

### Phase 3: GUI Integration
**Goal**: Update GUI to handle streaming updates

#### Step 3.1: Update TranslateSceneCommand
- [x] Connect to `batch_updated` event
- [x] Track already-processed lines to avoid redundant updates
- [x] Create `ViewModelUpdate` objects for partial updates
- [x] Handle summary updates appropriately
- [x] Test: Verify GUI updates in real-time during streaming
- [x] Test: Verify no duplicate updates occur

#### Step 3.2: Update ViewModelUpdate Processing
- [X] Ensure `ViewModelUpdate` can handle partial batch updates
- [X] Add logic to merge partial line updates efficiently
- [X] Test: Verify partial updates don't break view model consistency

### Phase 4: Error Handling & Edge Cases
**Goal**: Robust error handling for streaming scenarios

#### Step 4.1: Error Handling
- [X] Handle streaming interruptions gracefully
- [X] Ensure partial translations are preserved on error
- [X] Add proper abortion handling for streaming requests

#### Step 4.2: Edge Cases
- [X] Handle empty or malformed streaming responses
- [X] Handle responses that don't contain line breaks
- [X] Ensure proper cleanup on completion/error

# Phase 5: Add streaming support to more providers
- [X] Add streaming response support for AnthropicClient
- [X] Add streaming response support for GeminiClient
- [X] Add streaming response support for OpenRouterClient / CustomClient
- [ ] Add streaming response support for DeepSeekClient

### Phase 6: Testing & Validation
**Goal**: Comprehensive testing of streaming functionality

#### Step 6.1: Unit Tests
- [ ] Create unit tests for streaming event handling
- [ ] Create unit tests for partial response processing
- [ ] Create mock streaming client for testing
- [ ] Test: All streaming components in isolation

#### Step 6.2: Integration Tests
- [ ] Create integration tests with real OpenAI streaming
- [ ] Test streaming with various batch sizes
- [ ] Test streaming with different content types
- [ ] Test: Network interruption during streaming
- [X] Test: User abort during streaming
- [ ] Test: API errors during streaming
- [ ] Test: End-to-end streaming workflow

## Technical Details

### Event Flow
```
SubtitleTranslator.TranslateBatch()
├── RequestTranslation() with streaming callback
├── _request_translation() with streaming callback
├── _get_client_response() with streaming callback
│   ├── Non-streaming: simple API call and return
│   └── Streaming: event loop with delta accumulation
│       ├── For each complete line group detected:
│       │   ├── Create partial Translation object
│       │   └── Call streaming callback
│       └── Return final complete response
├── Streaming callback processes partial translations
├── For each callback:
│   ├── Emit batch_updated event
│   └── Update ViewModelUpdate
└── On completion: emit batch_translated event
```

### Key Design Decisions

1. **Partial Processing**: Only process accumulated response up to complete line groups (detected by blank lines in delta)
2. **No Validation**: Skip validation on partial updates to avoid false failures
3. **Event Segregation**: Separate `batch_updated` (streaming) from `batch_translated` (completion) events. batch_updated is only used for partial updates.
4. **Tracking**: Command tracks processed lines to avoid redundant GUI updates
5. **Fallback**: Non-streaming clients continue to work unchanged

### Configuration

New settings in Provider_OpenAI:
- `stream_responses` (bool): Enable streaming mode for supported models
- Setting will appear in GUI options when streaming is supported

### Testing Strategy

Each phase includes specific tests to validate functionality:
1. **Unit Tests**: Test individual components in isolation
2. **Integration Tests**: Test component interactions
3. **Regression Tests**: Ensure existing functionality remains intact
4. **Performance Tests**: Verify streaming doesn't degrade performance

## Progress Tracking

- [x] Phase 1: Core Infrastructure
- [x] Phase 2.1: OpenAI Reasoning Client Streaming
- [x] Phase 2.2: Provider Settings
- [x] Phase 3.1: Update TranslateSceneCommand
- [X] Phase 3.2: Update ViewModelUpdate Processing
- [ ] Phase 4: Error Handling & Edge Cases
- [ ] Phase 5: Testing & Validation

## Implementation Notes

### Completed Architecture

#### TranslationRequest Pattern
- **File**: `PySubtrans/TranslationRequest.py`
- **Purpose**: Encapsulates request state and streaming logic to avoid stateful clients
- **Key Methods**:
  - `ProcessStreamingDelta(delta_text)` - Main entry point for processing streaming deltas
  - `_emit_partial_update()` - Consolidated method that emits updates and marks processed
  - `_has_complete_line_group()` - Detects complete line groups via `\n\n` threshold

#### Event-Driven Streaming
- **Signal**: `batch_updated` in `TranslationEvents`
- **Flow**: delta → TranslationRequest → partial Translation → batch_updated event
- **Threshold**: Only emit for complete line groups (blank line separated)

#### OpenAI Responses API Integration
- **Events Used**: `response.output_text.delta`, `response.completed`, `response.failed`
- **Structure**: `event.response.output[0].content[0].text` for final response
- **Delta**: `event.delta` for streaming text chunks

#### Code Standards Applied
- **Naming**: PascalCase for public methods, `_snake_case` for private
- **Type Hints**: Proper spacing around colons (`param : str`)
- **Consolidation**: Eliminated duplicate `rfind('\n\n')` logic across methods

### Development Notes

- Implementation maintains backward compatibility
- Streaming should be opt-in via settings
- Error handling must be robust given network nature of streaming
- GUI updates should be efficient to avoid performance issues
- Testing should cover both happy path and edge cases thoroughly

### Phase 3 Implementation Notes

#### TranslateSceneCommand Updates
- **File**: `GuiSubtrans/Commands/TranslateSceneCommand.py`
- **Line Tracking**: Added `processed_lines` set to track `(scene, batch, line)` tuples and avoid redundant GUI updates
- **Event Connection**: Connected to `batch_updated` event in addition to existing `batch_translated` event
- **Streaming Callback**: Implemented `_on_batch_updated()` method that:
  - Only processes lines not yet seen to avoid redundant updates
  - Creates partial `ModelUpdate` objects with only new line translations
  - Excludes summary, context, errors from streaming updates (reserved for completion)
  - Tracks processed lines to ensure each translation appears only once in GUI
- **Event Cleanup**: Properly disconnects `batch_updated` event in finally block
- **Backward Compatibility**: Non-streaming translations continue to work unchanged via existing `_on_batch_translated()` method

#### ScenesView Expansion Collapse Fix
- **Problem**: `ProjectViewModel.ProcessUpdates()` called `layoutChanged.emit()` after every update batch, causing QTreeView to reset expansion states
- **Root Cause**: Data-only updates (like streaming line translations) don't require structural layout changes but were triggering full layout refresh
- **Solution**: Implemented selective signaling in `ProjectViewModel`:
  - Added `structural_changes_pending` flag to track when layout actually changes
  - Modified all structural operations (`AddScene`, `RemoveScene`, `AddBatch`, etc.) to set flag
  - Changed `ProcessUpdates()` to only emit `layoutChanged` when structural changes occurred
  - Data-only updates (like `UpdateLines`) skip `layoutChanged` emission entirely
- **Result**: Streaming updates now preserve ScenesView expansion states while maintaining proper signaling for structural changes
- **Testing**: Verified with test script - data-only updates emit no `layoutChanged`, structural updates emit `layoutChanged` as expected