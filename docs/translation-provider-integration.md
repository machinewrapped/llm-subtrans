# Translation Provider Integration

Translation providers adapt service-specific settings and model discovery to the shared translation flow. Providers live in `PySubtrans/Providers/`; their clients live in `PySubtrans/Providers/Clients/`.

## Provider and Client Roles

A `TranslationProvider` represents a service in the provider registry. It supplies provider options, discovers available models, validates settings, and creates a `TranslationClient`.

A `TranslationClient` makes requests to the service. It builds or sends translation prompts, receives responses, and supplies a `TranslationParser` to extract translated lines. `TranslationPrompt` combines user instructions, subtitle lines, context, and templates. `TranslationParser` matches response text to source lines, extracts metadata, and validates results.

## Model Discovery

Each provider owns a `ModelList` that tracks model lookup state:

- `Unloaded` - no lookup has completed
- `Loading` - an asynchronous lookup is in progress
- `Loaded` - the returned list is authoritative, including when it is empty
- `Failed` - the last lookup failed

The provider settings UI can show known models without starting a new lookup. Model discovery runs in a worker thread. Each lookup has a request token; results from a superseded or cancelled lookup are discarded. A failed lookup leaves the saved model selection usable.

## Streaming

A client exposes whether it supports streaming. Where supported, `stream_responses` enables streaming updates. `TranslationRequest` keeps state for a request while deltas arrive and emits partial batch updates as complete line groups become available.

Provider streaming implementations vary. Check the client implementation for service-specific request and event handling.

## Provider Settings UI

`SettingsDialog` builds global settings from its `SECTIONS` schema. It uses `OptionsWidgets.CreateOptionWidget` to create controls and `VISIBILITY_DEPENDENCIES` to define conditional visibility.

The provider settings tab obtains its options from the selected provider's `GetOptions` method. Model-dependent controls are populated when asynchronous model discovery completes. When the lookup succeeds, the selected model is retained if available or replaced with an available choice; on failure, the saved value is kept. Provider information is displayed through the shared `InformationOptionWidget`.

## Adding a Provider

1. Add a `TranslationProvider` subclass under `PySubtrans/Providers/`.
2. Implement provider options, model discovery, validation as needed, and client creation.
3. Implement the service API in a `TranslationClient` subclass under `PySubtrans/Providers/Clients/`.
4. Import the provider module in `PySubtrans/Providers/__init__.py` so it is registered at startup.