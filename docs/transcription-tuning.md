# Tuning Transcription Line Assembly

Transcription captures let developers replay provider output through the current line builder without transcribing the media again. The capture stores raw provider segments before line assembly.

Use the project virtual environment Python: `.\envsubtrans\Scripts\python.exe` on Windows or `./envsubtrans/bin/python` on Linux and macOS.

## Capture a Transcription

~~~text
.\envsubtrans\Scripts\python.exe scripts/transcribe.py media.mkv --capture capture.json
~~~

You can also set the capture destination with the `TRANSCRIPTION_CAPTURE_PATH` environment variable.

A capture also records the line settings the run assembled lines with, including the provider's merge gaps and timing correction. Replay uses them unless they are overridden on the command line. Older captures did not record them, so they replay with the current options and the provider's defaults.

## Replay and Compare

Replay a capture with the current line-building code:

~~~text
.\envsubtrans\Scripts\python.exe scripts/replay_transcription.py capture.json
~~~

The replay report includes line counts, short lines, lines shorter than their speech estimate, lines at the newline limit, word/transcript similarity, and timing-order statistics. Use `--quiet` to show summary output only.

Override builder settings to compare behavior without another transcription run:

~~~text
.\envsubtrans\Scripts\python.exe scripts/replay_transcription.py capture.json --min-line-duration 1.2
.\envsubtrans\Scripts\python.exe scripts/replay_transcription.py capture.json --quiet --compare min_line_seconds 0.6 0.8 1.0
~~~

`--source parts` and `--source words` force the builder to use provider parts or word timings when both are available. `--word-coverage` can override the provider's word coverage setting, and `--timing-correction-factor` its timing correction. Use `--help` for the available line-assembly settings.

Write the replayed lines as a subtitle file by specifying an output path; the extension selects the format:

~~~text
.\envsubtrans\Scripts\python.exe scripts/replay_transcription.py capture.json --quiet --output replayed.vtt
~~~

The output applies transcription post-processing by default. Use `--no-postprocess` to write the raw assembled lines.

## Line Assembly Components

`TranscriptionLineBuilder` turns provider segments into timed subtitle lines. Provider parts are used when available; otherwise parts are derived from the transcript. `WordAlignment` aligns word timings to transcript text, which remains the source for subtitle text. `TranscriptCutter` and `UtteranceSplitter` divide segments, while `LineMerger` combines or adjusts the resulting lines.

The line assembly code is independent of provider and audio dependencies, so captures can be replayed against it directly.

## Findings

- [transcription-timing-correction.md](transcription-timing-correction.md): lines too short for their text, and why `timing_correction_factor` extends rather than merges.