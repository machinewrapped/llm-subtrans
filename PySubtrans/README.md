# PySubtrans

PySubtrans is the subtitle translation engine that powers [LLM-Subtrans](https://github.com/machinewrapped/llm-subtrans). It provides tools to read and write subtitle files in various formats, connect to various LLMs as translators and manage a translation workflow.

This package makes these capabilities available as a library that you can incorporate into your own tools and workflows to take advantage of the best-in-class translation quality that LLM-Subtrans provides.

## Installation

Basic installation with support for OpenRouter, DeepSeek or any server with an OpenAI-compatible API.

```bash
pip install pysubtrans
```

Additional specialized provider integrations are delivered as optional extras, so that you only install the SDKs for providers you intend to use:

```bash
pip install pysubtrans[openai]
pip install pysubtrans[gemini]
pip install pysubtrans[claude]
pip install pysubtrans[openai,gemini,claude,mistral,bedrock]
```

## Quick start: translate a subtitle file

The quickest way to get started is to use the helper functions exposed at the package root. They wrap the objects used by LLM-Subtrans so that you can execute a full translation pipeline with a few lines of code.

```python
from PySubtrans import init_options, init_subtitles, init_translator

options = init_options(
    provider="OpenAI",
    model="gpt-5-mini",
    api_key="sk-your-api-key",
    prompt="Translate these subtitles into Spanish",
)

subtitles = init_subtitles("movie.srt")

translator = init_translator(options)
translator.Translate(subtitles)

subtitles.SaveTranslation("movie-translated.srt")
```

Subtitle format is auto-detected based on file extension.

## Configuration with `init_options`
`init_options` creates an `Options` instance and accepts additional keyword arguments for any of the fields documented in `Options.default_settings`. 

The Options class provides a wide range of options to configure the translation process.

Some that are particularly useful:

`max_batch_size`: controls how many lines will be sent to the LLM in one request. The default value (30) is very conservative, for maximum compatibility. Models like Gemini 2.5 Flash can easily handle batches of 150 lines or more, which allows for faster translation.

`scene_threshold`: subtitles are divided into scenes before batching, using this time value as a heuristic to indicate that a scene transition has happened. The default of 60 seconds is very coarse, and may end up with only one scene for dialogue heavy movies or dozens of scenes with only a few lines each for minimalist arthouse films. Depending on your use case, consider setting this very high and relying on the batcher instead.

`postprocess_translation`: Runs a pass on the translated subtitles to try to resolve some common problems introduced by translation, e.g. breaking long lines with newlines.

Example usage:

```python
from PySubtrans import init_options

options = init_options(
    provider="Gemini",
    model="gemini-2.5-flash",
    api_key="your-key",
    movie_name="French Movie",
    prompt="Translate these subtitles for {movie_name} into German, with cultural references adapted for a German audience",
    max_batch_size=150,
    scene_threshold=120
    temperature=0.3,
    postprocess_translation=True,
    break_long_lines=True,
    break_dialog_on_one_line=True,
    convert_wide_dashes=True
)
```

Note that there are a number of options which are only used by the GUI-Subtrans application and have no function in PySubtrans.

## Initialising Subtitles with `init_subtitles`

`init_subtitles` creates a `Subtitles` instance and optionally loads subtitle content from a file or string. It supports automatic format detection and handles multiple subtitle formats.

**Parameters:**
- `filepath`: Path to a subtitle file to load (mutually exclusive with `content`)
- `content`: Subtitle content as a string (mutually exclusive with `filepath`)

Format detection is automatic based on file extension or content analysis.

**Supported formats:** `.srt`, `.ass`, `.ssa`, `.vtt`

**Examples:**

Load subtitles from a file:
```python
from PySubtrans import init_subtitles

subtitles = init_subtitles(filepath="movie.srt")
```

Load subtitles from a string:
```python
srt_content = """1
00:00:01,000 --> 00:00:03,000
Hello world

2
00:00:04,000 --> 00:00:06,000
This is a test"""

subtitles = init_subtitles(content=srt_content)
```

## Preparing a `SubtitleTranslator` with `init_translator`

`init_translator` prepares a `SubtitleTranslator` instance that can be used to translate `Subtitles`. It uses the provided `Options` to initialise a `TranslationProvider` instance that connects to the chosen translation service.

Example

```python
from PySubtrans import init_translator
translator = init_translator({"provider": "gemini", "api_key": "your-key"})
translator.events.scene_translated += on_scene_translated  # Subscribe to events
translator.TranslateSubtitles(subtitles)
```

### Customising translation with custom instructions
 Custom instructions can be supplied via an `instruction_file` argument or by explicitly overriding `prompt` and `instructions`. 

`prompt` is a high level description of the task, whilst `instructions` provide detailed instructions for the model (as a system prompt, where possible).

This can include directions about how to handle the translation, e.g. "any profanity should be translated without censorship", or notes about the source subtitles (e.g. "the dialogue contains a lot of puns, these should be adapted for the translation").

It is *imperative* that the instructions contain examples of properly formatted output - see the default instructions for examples.

```
Your response will be processed by an automated system, so you MUST respond using the required format:

Example (translating to English):

#200
Original>
変わりゆく時代において、
Translation>
In an ever-changing era,

#501
Original>
進化し続けることが生き残る秘訣です。
Translation>
continuing to evolve is the key to survival.
```

Adapting the examples to your use case can greatly improve the model's performance by teaching it what good looks like.
  
See [LLM-Subtrans](https://github.com/machinewrapped/llm-subtrans/instructions) for examples of instructions tailored to specific use cases.

## Working with projects using `init_project`
`SubtitleProject` provides a higher level interface for managing a translation job, with methods to read and write a project file to disk and events to hook into on scene/batch translation.

`init_project` instantiates a `SubtitleProject` with a pre-initialised `SubtitleTranslator` and loads the source subtitles if a file path is supplied.

```python
from PySubtrans import init_project

# Create a project with translator ready to go
translation_settings = {
    'provider': 'OpenRouter',
    'model': 'qwen/qwen3-235b-a22b:free',
    'target_language': 'Spanish',
    'api_key': 'your-openrouter-api-key'
}

project = init_project('path_to_source_subtitles.srt', translation_settings=translation_settings)

# Translate the subtitles
project.TranslateSubtitles()

# Save the translation
project.SaveTranslation('output_subtitles.srt')
```

By default projects are only held in memory, but specifying `persistent=True` will write a `.subtrans` project file to disk (or reload an existing project), allowing a translation job to be resumed at a future time.

```python
# Create a persistent project that can be resumed later
project = init_project('subtitles.srt', persistent=True, translation_settings=translation_settings)
project.TranslateSubtitles()  # Progress is automatically saved
```

## Advanced workflows

PySubtrans is designed to be modular. The helper functions above are convenient entry points, but you are free to use lower-level components directly when you need more control:

### Building subtitles programmatically

#### Option 1: SubtitleBuilder for programmatic control

Use `SubtitleBuilder` when you want to build subtitles programmatically. 

```python
from PySubtrans import SubtitleBuilder
from datetime import timedelta

builder = SubtitleBuilder(max_batch_size=100)
subtitles = (builder
    .AddScene(summary="Opening dialogue")
    .BuildLine(timedelta(seconds=1), timedelta(seconds=3), "Hello, my name is...")
    .BuildLine(timedelta(seconds=4), timedelta(seconds=6), "Nice to meet you!")
    .BuildLine(timedelta(seconds=8), timedelta(seconds=10), "We need to talk.")

    .AddScene(summary="Action sequence")  # New scene
    .BuildLine(timedelta(seconds=65), timedelta(seconds=67), "Look out!")
    # ... 
    .Build()
)
```
Batching of subtitle lines within each scene is handled automatically.

#### Option 2: Automatic batching with SubtitleBatcher

`SubtitleBatcher` can be used to automatically group lines into scenes and batches:

```python
from PySubtrans import init_subtitles, init_options
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.SubtitleBatcher import SubtitleBatcher
from datetime import timedelta

# Initialize subtitles and add lines
subtitles = init_subtitles()
subtitles.originals = [
    SubtitleLine.Construct(1, timedelta(seconds=1), timedelta(seconds=3), "First line"),
    SubtitleLine.Construct(2, timedelta(seconds=4), timedelta(seconds=6), "Second line"),
    SubtitleLine.Construct(3, timedelta(seconds=30), timedelta(seconds=32), "After scene break"),
    #... all the lines for the translation job
]

# Use SubtitleBatcher to organize into scenes and batches
batcher = SubtitleBatcher({"scene_threshold" : 30, "max_batch_size" : 50})
subtitles.AutoBatch(batcher)
```

### Custom integrations

* Create a `Subtitles` instance by hand (for example when generating subtitles from a transcription pipeline) and pass it straight to `SubtitleTranslator.TranslateSubtitles`.
* Construct your own `TranslationProvider` instance or subclass to integrate bespoke APIs. All built-in providers live under `PySubtrans.Providers` and serve as reference implementations.
* Use `SubtitleBatcher` and `SubtitleBatch` to implement custom batching strategies when the default automatic batching does not fit your use case.
* Hook into `TranslationEvents` to monitor progress or feed translated scenes into additional post-processing steps.

For a detailed breakdown of the module layout and responsibilities refer to the [architecture guide](https://github.com/machinewrapped/llm-subtrans/blob/main/docs/architecture.md).

## Learning from LLM-Subtrans and GUI-Subtrans

The full [LLM-Subtrans](https://github.com/machinewrapped/llm-subtrans) and [GUI-Subtrans](https://github.com/machinewrapped/llm-subtrans/tree/main/GuiSubtrans) applications provide end-to-end examples that combine PySubtrans with logging, configuration UIs and persistence layers. They are excellent references when designing larger systems or when you want to replicate advanced features such as preview runs, retries or translation replays.

## License

PySubtrans is released under the MIT License. See [LICENSE](LICENSE) for details.
