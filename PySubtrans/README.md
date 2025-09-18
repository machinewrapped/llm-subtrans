# PySubtrans

PySubtrans is the subtitle preparation and translation engine that powers [LLM-Subtrans](https://github.com/machinewrapped/llm-subtrans). It provides everything required to parse subtitle files, manage translation projects, talk to large language model providers and post-process the resulting text. This package makes those capabilities available as a reusable Python library so you can compose your own translation workflows or integrate them into existing tools.

## Installation

```bash
pip install pysubtrans
```

Provider integrations are delivered as optional extras so you only install the SDKs you need:

```bash
pip install pysubtrans[openai]
pip install pysubtrans[gemini]
pip install pysubtrans[mistral]
```

The extras mirror the options that ship with LLM-Subtrans. Multiple extras can be installed in a single command: `pip install pysubtrans[openai,gemini]`.

## Quick start: translate a subtitle file

The quickest way to get started is to use the helper functions exposed at the package root. They wrap the objects used by LLM-Subtrans so that you can stand up a translation pipeline in a few lines of code.

```python
from PySubtrans import init_options, init_project, init_translator

options = init_options(
    provider="OpenAI",
    model="gpt-4o-mini",
    api_key="sk-your-api-key",
    instruction_file="instructions.txt",  # Optional – overrides the default prompt/instructions
    target_language="es",
)

project = init_project("movie.srt", persistent=True)
translator = init_translator(project, options)

project.TranslateSubtitles(translator)
project.SaveTranslation()  # Writes the translated subtitles to disk
```

The helpers return the same `Options`, `SubtitleProject` and `SubtitleTranslator` objects that power the main application, so you can continue to customise them as needed.

## Configuration with `init_options`

`init_options` creates an `Options` instance and accepts additional keyword arguments for any of the fields documented in `Options.default_settings`. A few examples:

```python
options = init_options(
    provider="Gemini",
    model="gemini-2.0-flash",
    api_key=os.environ["GOOGLE_API_KEY"],
    temperature=0.3,
    target_language="de",
    include_original=True,
)
```

* Provider credentials, endpoint details and model names can be passed directly. They will be moved into provider-specific settings automatically when the translator is created.
* Custom instructions can be supplied via `instruction_file` or by overriding `prompt`, `instructions` and `retry_instructions` explicitly.
* Any additional keyword arguments are merged into the returned `Options` instance, enabling full access to batching thresholds, formatting preferences, language metadata and more.

## Working with projects using `init_project`

`init_project` normalises the provided path, instantiates a `SubtitleProject` and loads the subtitles immediately if a file path is supplied. Passing `persistent=True` mirrors the CLI behaviour by enabling `.subtrans` project files that keep track of in-progress translations and settings.

You can continue to call the usual project helpers:

```python
project.SaveProjectFile()
project.SaveTranslation("/custom/output/path.srt")
project.UpdateProjectSettings(options)
```

When no file path is supplied the project is created without loading subtitles, making it easy to populate the `Subtitles` object programmatically before translation.

## Building translators with `init_translator`

`init_translator` validates the provider configuration, loads any instruction file declared in the options and wires up a ready-to-use `SubtitleTranslator`. Behind the scenes it uses `TranslationProvider.get_provider` to construct the correct provider client and applies your option overrides to the current project.

Once you have a translator you can:

```python
translator.events.scene_translated += handle_scene  # Subscribe to events
project.TranslateSubtitles(translator)
```

The returned `SubtitleTranslator` exposes all of the batching, retry and provider integration features from the main application.

## Advanced workflows

PySubtrans is designed to be modular. The helper functions above are convenient entry points, but you are free to use lower-level components directly when you need more control:

* Create a `Subtitles` instance by hand (for example when generating subtitles from a transcription pipeline) and pass it straight to `SubtitleTranslator.TranslateSubtitles`.
* Construct your own `TranslationProvider` instance or subclass to integrate bespoke APIs. All built-in providers live under `PySubtrans.Providers` and serve as reference implementations.
* Use `SubtitleBatcher` and `SubtitleBatch` to implement custom batching strategies when the default automatic batching does not fit your use case.
* Hook into `TranslationEvents` to monitor progress or feed translated scenes into additional post-processing steps.

For a detailed breakdown of the module layout and responsibilities refer to the [architecture guide](https://github.com/machinewrapped/llm-subtrans/blob/main/docs/architecture.md).

## Learning from LLM-Subtrans and GUI-Subtrans

The full [LLM-Subtrans](https://github.com/machinewrapped/llm-subtrans) and [GUI-Subtrans](https://github.com/machinewrapped/llm-subtrans/tree/main/GuiSubtrans) applications provide end-to-end examples that combine PySubtrans with logging, configuration UIs and persistence layers. They are excellent references when designing larger systems or when you want to replicate advanced features such as preview runs, retries or translation replays.

## License

PySubtrans is released under the MIT License. See [`PySubtrans/LICENSE`](LICENSE) for details.
