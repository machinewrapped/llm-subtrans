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

The quickest way to get started is to use the helper functions exposed at the package root. They wrap the classes used by LLM-Subtrans so that you can execute a full translation pipeline with a few lines of code.

```python
from PySubtrans import init_options, init_subtitles, init_translator

options = init_options(
    provider="Gemini",
    model="gemini-2.5-flash-lite",
    api_key="your-api-key",
    prompt="Translate these subtitles into Spanish"
    )

subtitles = init_subtitles("movie.srt", options=options)

translator = init_translator(options)
translator.TranslateSubtitles(subtitles)

subtitles.SaveTranslation("movie-translated.srt")
```

Subtitle format is auto-detected based on file extension or content.

## Basic Usage

### Working with a `SubtitleProject` with `init_project`

`SubtitleProject` provides a high level interface for managing a translation job, with methods to read and write a project file to disk and event hooks on scene/batch translation. This is the framework that LLM-Subtrans and GUI-Subtrans use to manage translation workflows, but it is general enough that it could be used in other contexts.

`init_project` instantiates a `SubtitleProject` and loads and prepares the source subtitles if a file path is supplied.

```python
from PySubtrans import init_options, init_project, init_translator

# Create a project and translate the subtitles
project_settings = init_options(
    provider='OpenRouter',
    model='qwen/qwen3-235b-a22b:free',
    target_language='Spanish',
    api_key='your-openrouter-api-key',
    preprocess_subtitles=True,
    scene_threshold=60,
    max_batch_size=100,
)

project = init_project(project_settings, filepath='path_to_source_subtitles.srt')

# Translate the subtitles
translator = init_translator(project_settings)
project.TranslateSubtitles(translator)

# Save the translation - filename is automatically generated
project.SaveTranslation()
```

By default projects are only held in memory, but specifying `persistent=True` will write a `.subtrans` project file to disk or reload an existing project, allowing a translation job to be resumed at a future time.

```python
# Create a persistent project that can be resumed later
project = init_project(project_settings, filepath='subtitles.srt', persistent=True)
# ... do some work
project.SaveProject()  # Progress is automatically saved
```

### Initialising Subtitles directly with `init_subtitles`

`init_subtitles` creates a `Subtitles` instance, optionally loading subtitle content from a file or string. It auto-detects the format and, by default, prepares the subtitles for translation.

**Parameters:**
- `filepath`: Path to a subtitle file to load (mutually exclusive with `content`)
- `content`: Subtitle content as a string (mutually exclusive with `filepath`)
- `options`: Optional `Options` instance providing preprocessing and batching settings

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

By default `init_subtitles` preprocesses and batches subtitles to be ready for translation, using the provided `options`. See `batch_subtitles` for details.

### Initialising a `SubtitleTranslator` with `init_translator`
`init_translator` prepares a `SubtitleTranslator` instance that can be used to translate `Subtitles`. It uses the provided `Options` to initialise a `TranslationProvider` instance to connect to the chosen translation service.

If you want to validate provider credentials and connection details before starting work, call `init_translation_provider` first and pass the resulting provider into `init_translator`. This pattern lets you fail fast when credentials are missing or incorrect and reuse the same provider instance across multiple translators.

Instantiating your own `SubtitleTranslator` allows you to have more fine-grained control over the translation process, e.g. translating individual scenes or batches. You can subscribe to `events` to receive notifications when individual scenes or batches have been translated to provide realtime feedback or further processing.

Subtitles must be batched prior to translation.

Example

```python
from PySubtrans import init_options, init_translator, init_translation_provider

options = init_options(provider="gemini", api_key="your-key")
provider = init_translation_provider("gemini", options)
translator = init_translator(options, translation_provider=provider)
translator.events.scene_translated += on_scene_translated  # Subscribe to events
translator.TranslateSubtitles(subtitles)
```

Note that different providers may require different settings. See the [LLM-Subtrans](https://github.com/machinewrapped/llm-subtrans/) documentation for details on supported providers.

### Configuration with `init_options`

`init_options` creates an `Options` instance and accepts additional keyword arguments for any of the fields documented in `Options.default_settings`. 

The Options class provides a wide range of options to configure the translation process. The default values should work well for most use cases, but some are definitely worth experimenting with.

`max_batch_size`: controls how many lines will be sent to the LLM in one request. The default value (30) is very conservative, for maximum compatibility. Models like Gemini 2.5 Flash can easily handle batches of 150 lines or more, which allows for faster translation.

`scene_threshold`: subtitles are divided into scenes before batching, using this time value as a heuristic to indicate that a scene transition has happened. The default of 60 seconds is very coarse, and may end up with only one scene for dialogue heavy movies or dozens of scenes with only a few lines each for minimalist arthouse films. Depending on your use case, consider setting this very high and relying on the batcher instead.

`postprocess_translation`: Runs a pass on the translated subtitles to try to resolve some common problems introduced by translation, e.g. breaking long lines with newlines. The post-processor can perform a range of operations, each of which is enabled by another setting, e.g. `break_dialog_on_one_line`, `normalise_dialog_tags`, `whitespaces_to_newline`, `remove_filler_words`.

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
    scene_threshold=120,
    temperature=0.3,
    postprocess_translation=True,
    break_long_lines=True,
    break_dialog_on_one_line=True,
    convert_wide_dashes=True
)
```

Note that there are a number of options which are only used by the GUI-Subtrans application and have no function in PySubtrans.

## Advanced workflows

PySubtrans is designed to be modular. The helper functions above are convenient entry points, but you are free to use lower-level components directly when you need more control:

### Explicitly initialising a `TranslationProvider`

`init_translator` will automatically construct a `TranslationProvider` based on the provided options, but it may be useful to construct one explicitly as each supported provider presents slightly different options.

```python
  from PySubtrans import SubtitleTranslator, SettingsType
  from PySubtrans.Providers.Provider_OpenRouter import
  OpenRouterProvider

  openrouter = OpenRouterProvider(SettingsType({
      'api_key': 'your_openrouter_api_key',
      'use_default_model': False,
      'model_family': "Google",  # Note: should be 
  "Google" not "Gemini"
      'model': "Gemini 2.5 Flash Lite",
      'temperature': 0.2
  }))

translator = SubtitleTranslator(settings, openrouter)
```

A provider can be constructed once and then used to initalise multiple `SubtitleTranslator` instances.

### Preprocessing subtitles with `preprocess_subtitles`

`preprocess_subtitles` can adjust the source subtitles using various heuristics to help produce more translatable subtitles.

**Duration and timing adjustments:**
- `merge_line_duration`: Merge lines with very short durations into the previous line
- `max_line_duration`: Split lines longer than specified duration (using punctuation as a guide)
- `min_split_chars`: Minimum characters required for splitting lines
- `min_line_duration`: Minimum duration for split lines
- `min_gap`: Ensure minimum gap between subtitle lines

**Text processing:**
- `whitespaces_to_newline`: Convert whitespace blocks to newlines (Chinese subtitles often separate dialog lines with multiple spaces, which confuses the translation)
- `break_dialog_on_one_line`: Detect mid-line dialog markers and add line breaks (helps the models recognise they are separate speakers, not just a dash in the line)
- `normalise_dialog_tags`: If one line of a multiline subtitle has a dialog marker, add it to the other(s)
- `remove_filler_words`: Remove specified filler words from text
- `filler_words`: Comma-separated list of filler words to remove (err, umm, ah, etc.)
- `full_width_punctuation`: Ensure full-width punctuation is used in Asian languages
- `convert_wide_dashes`: Convert wide dashes (emdash) to standard dashes (an anti-GPT pill)

### Batching subtitles manually with `batch_subtitles`

`Subtitles` must be batched before translation, so if the subtitles were not automatically batched via `init_subtitles` or `init_project` you can call `batch_subtitles` explcitly instead. This returns a list of `SubtitleScene` containing the batched subtitles.

The parameters are:

`scene_threshold`: A new scene will be introduced after a gap of N seconds.
`max_batch_size`: If a scene contains too more lines than this it will be subdivided into batches until each batch is no larger than this.
`min_batch_size`: More of a suggestion than a rule, batches are primarily divided to maximise temporal cohesion of each batch.
`prevent_overlap`: If the end time of a subtitle overlaps the start time of the next subtitle it will be reduced to ensure that there is no overlap.

```python
from PySubtrans import batch_subtitles, init_subtitles

subtitles = init_subtitles("movie.srt", auto_batch=False)
batch_subtitles(subtitles, scene_threshold=90.0, min_batch_size=2, max_batch_size=40)

print(f"Created {subtitles.scenecount} scenes")
```

### Building subtitles programmatically

Use `SubtitleBuilder` when you want to build subtitles programmatically. 

```python
from PySubtrans import Subtitles, SubtitleBuilder
from datetime import timedelta

builder = SubtitleBuilder(max_batch_size=100)
subtitles : Subtitles = (builder
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

### Preparing subtitles with SubtitleBatcher
`SubtitleBatcher` can be used to automatically group lines into scenes and batches:

```python
from PySubtrans import Subtitles, SubtitleLine, SubtitleBatcher
from datetime import timedelta

# Initialize subtitles and add lines
lines = [
    SubtitleLine.Construct(1, timedelta(seconds=1), timedelta(seconds=3), "First line"),
    SubtitleLine.Construct(2, timedelta(seconds=4), timedelta(seconds=6), "Second line"),
    SubtitleLine.Construct(3, timedelta(seconds=30), timedelta(seconds=32), "After scene break"),
    #... all the lines for the translation job
]

subtitles = Subtitles()
batcher = SubtitleBatcher({"scene_threshold" : 30, "max_batch_size" : 50})
subtitles.scenes = batcher.BatchSubtitles(lines)
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

### A programmatic workflow example
This example shows how to construct subtitles and translate them with progress feedback, working directly with the PySubtrans business logic.

```python
import json
from datetime import timedelta
from PySubtrans import SubtitleBuilder, Options, SubtitleTranslator, TranslationProvider, SubtitleError

# Sample data with scene markers
json_data = {
    "movie_name": "Sample Film",
    "description": "A sample film for demonstration",
    "scenes": [
        {
            "summary": "Opening scene",
            "lines": [
                {"start": "00:00:01.000", "end": "00:00:03.000", "text": "Hello world"},
                {"start": "00:00:04.000", "end": "00:00:06.000", "text": "How are you?"}
            ]
        },
        {
            "summary": "Action sequence",
            "lines": [
                {"start": "00:01:05.000", "end": "00:01:07.000", "text": "Look out!"},
                {"start": "00:01:08.000", "end": "00:01:10.000", "text": "Watch out!"}
            ]
        }
    ]
}

# Build subtitles programmatically
builder = SubtitleBuilder(max_batch_size=5)

for scene_data in json_data["scenes"]:
    builder.AddScene(summary=scene_data["summary"])

    for line_data in scene_data["lines"]:
        builder.BuildLine(
            start=line_data["start"],
            end=line_data["end"],
            text=line_data["text"]
        )

subtitles = builder.Build()

# Configure translator with progress tracking
options = Options({
    'provider': "OpenAI",
    'model': "gpt-5-mini",
    'api_key': "your-api-key",
    'prompt': f"Translate subtitles for {json_data['movie_name']} into Spanish",
    'max_batch_size': 5
})

translation_provider = TranslationProvider.get_provider(options)
if not translation_provider.ValidateSettings():
    raise SubtitleError(translation_provider.validation_message)
    
translator = SubtitleTranslator(options, translation_provider)

# Set up event handlers for real-time feedback
def on_batch_translated(batch):
    print(f"Translated batch {batch.number} in scene {batch.scene} ({batch.size} lines)")
    if batch.summary:
        print(f"  Summary: {batch.summary}")

def on_scene_translated(scene):
    print(f"Completed scene {scene.number}: {scene.summary}")
    print(f"   Total: {scene.linecount} lines in {scene.size} batches")

# Subscribe to translation events
translator.events.batch_translated += on_batch_translated
translator.events.scene_translated += on_scene_translated

# Execute translation with progress feedback
print(f"Starting translation of {subtitles.linecount} lines...")
translator.TranslateSubtitles(subtitles)
print("\nTranslation completed!")
```

### Using SubtitleEditor to manipulate `Subtitles`

`SubtitleEditor` provides a context manager for modifying `Subtitles` in a thread-safe manner:

```python
from PySubtrans import SubtitleEditor

subtitles = [...]

with SubtitleEditor(subtitles) as editor:
    # Update scene metadata
    editor.UpdateScene(scene_number = 1, update = {"summary": "Opening dialogue"})

    # Split scene 1 at batch 2 (creates a new scene)
    editor.SplitScene(scene_number = 1, batch_number = 2)

    # Merge batches 1 and 2 in scene 3
    editor.MergeBatches(scene_number = 3, batch_numbers = [1, 2])

    # Merge lines 100 and 101 within batch (2, 1)
    editor.MergeLinesInBatch(scene_number = 2, batch_number = 1, line_numbers = [100, 101])

print(f"Final state: {subtitles.scenecount} scenes, {subtitles.linecount} lines")
```

## Learning from LLM-Subtrans and GUI-Subtrans

There are many possible and correct ways to use PySubtrans. [LLM-Subtrans](https://github.com/machinewrapped/llm-subtrans) and [GUI-Subtrans](https://github.com/machinewrapped/llm-subtrans/tree/main/GuiSubtrans) provide two complete end-to-end examples that use PySubtrans in different ways, making use of different workflows and features. They can be used as a reference when integrating PySubtrans into your application if you want to use more advanced features.

### Batch automation example

The repository also includes [`scripts/batch_translate.py`](../scripts/batch_translate.py) as a ready-to-run batch sample. The script shows how to:

- build an `Options` instance with `init_options`, including command line overrides for provider, model and preview settings,
- walk a source directory using `SubtitleFormatRegistry.enumerate_formats()` to filter files that PySubtrans can translate,
- load subtitles with `init_subtitles`, initialise a `TranslationProvider` and `SubtitleTranslator`, and subscribe to translator events to provide live progress feedback, and
- save translations to a mirrored directory structure while writing a detailed execution log to disk.

Existing translations are skipped automatically, allowing you to resume long-running jobs without reprocessing completed files.

Preview mode can be enabled with `--preview` to exercise the entire pipeline without sending requests to a translation provider, which is helpful for smoke-testing workflows or validating settings.

_Documentation opportunity_: a dedicated README section covering translator events and preview mode would complement the sample script and make it easier for new users to discover these features without reading the source code.

## If you need to know more

For a more complete breakdown of the module layout and responsibilities of the various components of PySubtrans refer to the LLM-Subtrans [architecture guide](https://github.com/machinewrapped/llm-subtrans/blob/main/docs/architecture.md).

## License

PySubtrans is released under the MIT License. See [LICENSE](LICENSE) for details.
