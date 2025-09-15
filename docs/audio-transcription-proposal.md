# Audio-Transcription Support Implementation Proposal

## The motivation
Currently LLM-Subtrans provides best-in-class translation of subtitles from one language to another, but it requires text subtitles in the source language to operate.

It is possible to produce source subtitles externally using applications like Whisper and then translate those, but this requires the use of another tool and can low quality transcriptions lead to bad translations.

We would like to add native support for transcribing audio, especially audio extracted from a video file.

## Requirements

Transcription should be a separate option accessible from the MainToolbar, which opens a UI interface dedicated to transcription.

The user should be able to select an audio or video file and a transcription service, initiate the transcription and view summary details of the process as it proceeds.

The result should be a SubtitleProject initialised with the transcription and configured with the NewProjectSettings dialog, from which the user can proceed on to translation.

If a video file contains multiple audio streams the user should be presented with a drop-down to select the stream for transcription.

We should avoid dependencies on external tools like ffmpeg if possible, the app should be a self contained transcription-translation ecosystem.

## Initial phase
The initial phase is one of discovery and proof of concept:
- Research options for extracting audio streams from video files
    - Minimum requirement is MKV file support
    - MP4 file format would be a very welcome bonus
- Research options for transcription services.
    - Qwen Audio (https://qwen.ai/blog?id=41e4c0f6175f9b004a03a07e42343eaaf48329e7&from=research.latest-advancements-list, https://huggingface.co/Qwen/Qwen-Audio) seems promising
    - Gemini Audio Understanding could be a good alternative (https://ai.google.dev/gemini-api/docs/audio)
    - OpenRouter provides a number of audio to text capable models via their API (https://openrouter.ai/models?fmt=cards&input_modalities=audio&output_modalities=text)
- We should support API-based transcription, as this is inherently cross-platform and should work for users who cannot host a viable model locally
    - We should consider supporting local transcription as well, for users who have the hardware, but this is a secondary use case
- Research transcription formats offered by these services, and consider whether we need to implement a custom SubtitleFileHandler to support them 
    - It seems probably that the VTT support we already have is enough
- Consider whether we should extend the internal Subtitle class and SubtitleTranslator, SubtitlePrompt etc. to include metadata such as speaker ids, to help the translation service
- Determine what new classes and modules we need to add to the project.
    - Transcription should be provided as a service by the PySubtitle module
    - The interface to control transcription should be part of the GUI module.
    - CLI support can be considered later, maybe a simple --transcribe option that changes the flow of llm-subtrans.py

