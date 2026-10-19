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

## Provider Kinds

Each provider sets a `kind` class attribute from `ProviderKind`. The GUI groups the provider selector by kind under headings:

- `Direct` - a model maker's own API (the default)
- `Platform` - a cloud platform hosting models from several makers, such as Azure or Bedrock
- `Gateway` - a router or aggregator in front of other providers
- `Custom` - a server the user configures themselves

## Adding a Gateway

Gateways are defined as data rather than code. Each gateway is a module in `PySubtrans/Providers/Gateways/` containing a `GatewayDefinition` and a subclass that sets it:

```python
EXAMPLE = GatewayDefinition(name="Example", ...)

class ExampleProvider(GatewayProvider):
    definition = EXAMPLE
```

Import the module in `PySubtrans/Providers/Gateways/__init__.py` so it is registered at startup.

`GatewayProvider` takes the provider name, default model, settings and `<ENV_PREFIX>_*` environment defaults from the definition. It handles fetching the model list, the provider options, and client creation.

The definition's `ModelCatalogue` describes the model list and parses it: its path and whether it needs the API key, where the list and model IDs are found, how models are grouped into families, and which entries to filter out. A gateway whose catalogue cannot be described this way can override `GatewayProvider._parse_catalogue`.

`protocol` selects the request protocol. `GatewayProtocol.ChatCompletions` is the only one so far. A gateway that needs another protocol adds a `GatewayProtocol` member and a matching case in `GatewayProvider._create_client`, rather than a new provider class.

Then add a readme section. The shared gateway tests in `tests/IntegrationTests/test_GatewayProvider.py` cover every registered gateway; add a test there only for catalogue parsing the definition cannot describe.

A gateway is only merged once it has been tested against the live service. The maintainers usually don't have an account with each gateway, so the contributor tests it and reports in the pull request that:

- the model list loads with an API key, and unsuitable models are filtered out
- a short subtitle file translates with the default model and one other, with streaming on and off
- the command line works with the `<ENV_PREFIX>_API_KEY` environment variable

Never post an API key in a pull request or issue.

## Adding a Provider

1. Add a `TranslationProvider` subclass under `PySubtrans/Providers/` with a `name` and `kind`.
2. Implement provider options, model discovery, validation as needed, and client creation.
3. Implement the service API in a `TranslationClient` subclass under `PySubtrans/Providers/Clients/`.
4. Import the provider module in `PySubtrans/Providers/__init__.py` so it is registered at startup.

Only classes that define their own `name` are registered, so an intermediate base class such as `GatewayProvider` leaves it undefined.