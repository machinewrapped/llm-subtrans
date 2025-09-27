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
- [ ] Add `batch_updated` signal to `TranslationEvents`
- [ ] Test: Verify new signal can be created and connected

#### Step 1.2: Extend TranslationClient Base Class
- [ ] Add `supports_streaming` property to `TranslationClient`
- [ ] Add streaming callback parameter to `RequestTranslation()` and `_request_translation()`
- [ ] Update method signatures to support optional streaming callbacks
- [ ] Test: Verify base class changes don't break existing functionality

#### Step 1.3: Update SubtitleTranslator
- [ ] Add streaming callback handler to `TranslateBatch()`
- [ ] Implement partial response processing logic
- [ ] Add logic to emit `batch_updated` events for complete line groups
- [ ] Ensure validation only occurs on complete responses
- [ ] Test: Verify non-streaming translations still work correctly

### Phase 2: OpenAI Streaming Implementation
**Goal**: Implement streaming for OpenAI Reasoning Client

#### Step 2.1: OpenAI Reasoning Client Streaming
- [ ] Add streaming support detection to `OpenAIReasoningClient`
- [ ] Implement `_get_client_response()` method to handle streaming vs non-streaming
- [ ] Add delta accumulation and processing logic to detect complete line groups
- [ ] Implement partial translation creation and final response formatting
- [ ] Test: Verify streaming requests work with OpenAI API
- [ ] Test: Verify fallback to non-streaming for unsupported models

#### Step 2.2: Provider Settings
- [ ] Add `enable_streaming_responses` setting to `Provider_OpenAI`
- [ ] Add GUI option for streaming responses
- [ ] Test: Verify setting can be toggled and persists

### Phase 3: GUI Integration
**Goal**: Update GUI to handle streaming updates

#### Step 3.1: Update TranslateSceneCommand
- [ ] Connect to `batch_updated` event
- [ ] Track already-processed lines to avoid redundant updates
- [ ] Create `ViewModelUpdate` objects for partial updates
- [ ] Handle summary updates appropriately
- [ ] Test: Verify GUI updates in real-time during streaming
- [ ] Test: Verify no duplicate updates occur

#### Step 3.2: Update ViewModelUpdate Processing
- [ ] Ensure `ViewModelUpdate` can handle partial batch updates
- [ ] Add logic to merge partial line updates efficiently
- [ ] Test: Verify partial updates don't break view model consistency

### Phase 4: Error Handling & Edge Cases
**Goal**: Robust error handling for streaming scenarios

#### Step 4.1: Error Handling
- [ ] Handle streaming interruptions gracefully
- [ ] Ensure partial translations are preserved on error
- [ ] Add proper abortion handling for streaming requests
- [ ] Test: Network interruption during streaming
- [ ] Test: User abort during streaming
- [ ] Test: API errors during streaming

#### Step 4.2: Edge Cases
- [ ] Handle empty or malformed streaming responses
- [ ] Handle responses that don't contain line breaks
- [ ] Ensure proper cleanup on completion/error
- [ ] Test: Various malformed streaming responses
- [ ] Test: Streaming with very short responses
- [ ] Test: Streaming with very long responses

### Phase 5: Testing & Validation
**Goal**: Comprehensive testing of streaming functionality

#### Step 5.1: Unit Tests
- [ ] Create unit tests for streaming event handling
- [ ] Create unit tests for partial response processing
- [ ] Create mock streaming client for testing
- [ ] Test: All streaming components in isolation

#### Step 5.2: Integration Tests
- [ ] Create integration tests with real OpenAI streaming
- [ ] Test streaming with various batch sizes
- [ ] Test streaming with different content types
- [ ] Test: End-to-end streaming workflow

#### Step 5.3: Performance Testing
- [ ] Measure streaming vs non-streaming performance
- [ ] Test with large batches and long responses
- [ ] Verify memory usage is reasonable
- [ ] Test: Performance regression analysis

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
3. **Event Segregation**: Separate `batch_updated` (streaming) from `batch_translated` (completion) events
4. **Tracking**: Command tracks processed lines to avoid redundant GUI updates
5. **Fallback**: Non-streaming clients continue to work unchanged

### Configuration

New settings in Provider_OpenAI:
- `enable_streaming_responses` (bool): Enable streaming mode for supported models
- Setting will appear in GUI options when streaming is supported

### Testing Strategy

Each phase includes specific tests to validate functionality:
1. **Unit Tests**: Test individual components in isolation
2. **Integration Tests**: Test component interactions
3. **Regression Tests**: Ensure existing functionality remains intact
4. **Performance Tests**: Verify streaming doesn't degrade performance

## Progress Tracking

- [ ] Phase 1: Core Infrastructure
- [ ] Phase 2: OpenAI Streaming Implementation
- [ ] Phase 3: GUI Integration
- [ ] Phase 4: Error Handling & Edge Cases
- [ ] Phase 5: Testing & Validation

## Notes

- Implementation should maintain backward compatibility
- Streaming should be opt-in via settings
- Error handling must be robust given network nature of streaming
- GUI updates should be efficient to avoid performance issues
- Testing should cover both happy path and edge cases thoroughly