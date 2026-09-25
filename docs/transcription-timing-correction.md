# Transcription Timing Correction: Findings

This records what was learned about lines that are too short for their text, while working on [#460](https://github.com/machinewrapped/llm-subtrans/issues/460). It explains why `timing_correction_factor` works the way it does, and why it defaults to 0.

## Background

#460 proposed treating full stops as sentence ends for parts derived from a transcript (Gemini, Qwen Local, OpenAI word timestamps). A trial on the #459 branch split La Madre Muerta (Gemini) into more, shorter lines, and blind assessment rejected it. The main complaint was lines too fast to read, such as `Cuando estoy nerviosa es aún peor.` in 1.4 s. Each sentence was timed by its own words only, so the pause after it belonged to no line.

The issue proposed merging lines that are too fast to read into a neighbour. This investigation tested that, found it was the wrong fix, and replaced it with extending the line into the pause after it. Full stops as sentence ends were then assessed again with the correction in place, and rejected again, for the reasons below.

## Full stops are soft boundaries

Full stops do not end a part the way `?`, `!` and `。` do, but they are not ignored. `.` is in `CLAUSE_END_CHARS`, so when a part runs over the length or duration limit, `UtteranceSplitter.FitUtterance` prefers to split it at a full stop. A full stop is a good place to split a line that is too long, but not a reason to split one that is not.

No reason for this was recorded when it was written. The sentence-end set arrived with the first transcription commit (35a1bb3), and d6fc4b7 called a period "not a hard boundary" without saying why. The reason now comes from testing hard full-stop boundaries twice:

- **#459:** blind assessment split 2–2. The complaints were lines too fast to read, short sentences stranded at the 0.8 s minimum, and glued text.
- **With the correction at 0.7:** two 25-minute windows of La Madre Muerta, two Haiku assessors each, compared `main` against full stops. `main` won 3–1. The work is kept in a git stash, "transcription-full-stops".

The correction fixed the timing, but two problems remained, and neither is about timing:

- **Short consecutive sentences read better together.** `No hay prisa.`, `Eso es.` and `Hija puta.` became lines of their own at the 0.8 s minimum. Their speaking-time estimate is under 0.8 s, so the correction rightly leaves them alone. In `main` they share a line with the sentence beside them, like `David, ven. Rafa, llévatelos.`, which an assessor singled out as better.
- **Gemini's glued text relies on the speaker-change cut.** Gemini returned no word timing for `Ánimo` in `…Tú te la llevas. Ánimo.Nadie debía saber nada.`, and wrote no space after it. In `main`, the cut at the speaker change gives the unmatched text to the word before it, so `Ánimo.` stays with its speaker at 01:10:53. With full stops, `Ánimo.Nadie debía saber nada.` is one sentence, so `Ánimo` took the timing and speaker of `Nadie`, 22 s later.

Two concerns about full stops were also raised on #459, and still apply to any use of them as sentence ends:
- **Abbreviations.** Initials (`J.`) and dotted abbreviations (`U.S.A.`, `e.g.`) do not end a sentence under `SentenceEnds.ALL`. Titles such as `Dr.` and `Mr.` cannot be recognised by their shape, and are tracked in #463.
- **Duplicating `SubtitleProcessor`.** Where only text is available, `SubtitleProcessor` already splits lines over the duration limit, so the transcription should not add a second text-only splitter.

## Measuring "too short for its text"

The measure is a line's duration against `EstimateSpeechSeconds(text)`, never a characters-per-second rate. The estimate already allows for the script: syllabic characters take 0.2 s each, other alphanumerics 0.07 s.

The syllabic rate is a median, so about half of all real lines are shorter than their estimate. The useful signal is the tail. The captures in `transcription_tests/` were replayed with `scripts/replay_transcription.py` at the builder defaults:

| Capture | Lowest 1% | Lowest 5% | Lowest 10% | Lines below 0.5× |
|---|---|---|---|---|
| Fist of Fury, OpenRouter (MAI Transcribe 2) | 0.54 | 0.64 | 0.70 | 6 of 1,417 |
| La Madre Muerta, Gemini | 0.56 | 0.65 | 0.70 | 1 of 519 |
| La Madre Muerta, Gemini, full stops simulated | 0.55 | 0.63 | 0.68 | 3 of 603 |
| Fist of Fury, Qwen Local | 0.29 | 0.52 | 0.62 | 57 of 1,383 |

MAI's timings are accurate, and its lines are distributed the same way as Gemini's on La Madre. The issue's example is 0.70× its estimate, which is where MAI's lowest 10% of lines sit: people talking fast. The estimate cannot tell a squeezed Gemini line from fast speech in that range.

## What the lines below 0.5× actually are

Listing every line under 0.5× showed that none of them is fixed by merging:

- **OpenRouter (MAI):** four of the six are duplicate transcriptions of the same line (`你肾亏啊，真。` / `你神快啊，真。`), so the estimate counts the text twice. The other two are fast Cantonese.
- **Qwen Local:** the forced aligner loses the opening words of an utterance. The line keeps its text but starts 0.5–2.6 s after OpenRouter hears the same words, and the next line starts immediately after it. In the worst cases a whole stretch is crammed into a moment: 0.8 s for text estimated at 18 s. The missing time is before the line, not after it.
- **Muse:** single interjections reported as 0.08–0.16 s turns, already below `min_line_seconds`.
- **Gemini:** lines at or near the 0.80 s floor, where Gemini's zero-length word timings gave a shorter span still.

## Merging was the wrong fix

The first implementation counted a line under `factor × estimate` as a sliver, so the existing merge logic took it. At factor 0.5 it changed almost nothing: 1 line on Fist of Fury Gemini and none elsewhere. At 0.8 on La Madre with full stops it merged 25 lines, mostly recombining one speaker's consecutive sentences, which undid the full-stop split.

Merging only runs forwards, so a line too short for its text cannot join the readable line before it, even when that is the obvious partner. This is deliberate. Letting readable lines take on fragments stacked them into long, dense subtitles (d5a52f0), and the reason is now recorded in `LineMerger._sliver_runs`.

`_extends_instead` chooses between extending a fragment and merging it into dialogue with the next speaker. Basing that choice on the corrected speaking time instead of `min_line_seconds` gave identical output on every capture and factor. A fragment under 0.8 s rarely has an estimate large enough for the factor to matter, so the choice was left on `min_line_seconds`.

## Extending into the pause

The issue's own diagnosis was that the pause after a sentence no longer belonged to any line. The correction therefore extends a line too short for its text into the pause after it, towards `factor × estimate`:

- only the end moves, so a subtitle never appears before its speech;
- it stops `min_gap` before the next line, and at the chunk's end;
- it never shortens a line, merges lines or splits them;
- a correction under `MIN_TIMING_CORRECTION` (50 ms) is skipped, since it is imperceptible.

Without the threshold, about 40% of the changes at 0.6 were under 50 ms, so an assessment would have been comparing differences no viewer could notice.

Results with the threshold ("Extended" counts lines whose end moved):

| Capture | Factor | Extended | Median added | Max added | < 0.5× | < 0.6× | < 0.7× |
|---|---|---|---|---|---|---|---|
| OpenRouter (MAI), 1,417 lines | 0 | – | – | – | 6 | 34 | 137 |
| | 0.6 | 16 | 0.16 s | 0.44 s | 4 | 21 | 137 |
| | 0.7 | 81 | 0.16 s | 0.88 s | 4 | 10 | 69 |
| Qwen Local, 1,383 lines | 0 | – | – | – | 57 | 122 | 236 |
| | 0.6 | 59 | 0.16 s | 0.83 s | 34 | 88 | 236 |
| | 0.7 | 125 | 0.19 s | 1.24 s | 34 | 66 | 151 |
| Muse, 886 lines | 0 | – | – | – | 7 | 15 | 37 |
| | 0.6 | 6 | 0.28 s | 0.32 s | 2 | 12 | 37 |
| Fist of Fury Gemini, 4 usable chunks, 875 lines | 0 | – | – | – | 19 | 59 | 148 |
| | 0.6 | 36 | 0.10 s | 0.32 s | 0 | 30 | 148 |
| | 0.7 | 101 | 0.18 s | 0.58 s | 0 | 3 | 68 |
| | 0.8 | 226 | 0.22 s | 0.92 s | 0 | 3 | 8 |
| La Madre Muerta Gemini, 519 lines | 0 | – | – | – | 1 | 11 | 54 |
| | 0.6 | 6 | 0.15 s | 0.22 s | 0 | 5 | 54 |
| | 0.7 | 36 | 0.14 s | 0.46 s | 0 | 0 | 26 |
| | 0.8 | 83 | 0.22 s | 0.98 s | 0 | 0 | 7 |
| La Madre Muerta Gemini, full stops simulated, 603 lines | 0 | – | – | – | 3 | 17 | 71 |
| | 0.6 | 9 | 0.17 s | 0.22 s | 0 | 9 | 71 |
| | 0.7 | 46 | 0.15 s | 0.46 s | 0 | 1 | 35 |

Every line under 0.5× is measured against the same estimate the extension aims for, so the tail counts are bound to fall. They show the mechanism works, not that the output reads better. No blind assessment has been run.

For Gemini, 0.6 changes 1–4% of lines by a median of 0.10–0.17 s. 0.7 clears the tail under 0.6×, touching 7–12% of lines by up to about 0.5 s. At 0.8 it extends about a quarter of lines by up to a second, which is reading time rather than correction.

Qwen's lines under 0.5× bottom out at 34 whatever the factor. They are the late starts, which extension cannot reach.

## Decisions

- **`timing_correction_factor` defaults to 0 for every provider.** Heuristics that overrule a provider are applied only where it has shown a need, and nothing has been assessed yet. Gemini at 0.6–0.7 is the likely candidate.
- **It is a per-provider setting**, read with `settings.get_float` and shown in each provider's line options, so users can tune it.
- **Reading time is left to `extend_short_subtitles`**, which runs when a translation is saved. Timings are then adjusted for the final text, and the stored project is not changed irreversibly. The correction here addresses squeezed speaking time only.
- **`WordCoverage` stays separate.** Words missing whole stretches of the transcript is a difference in kind, and decides which heuristics apply. The correction factor is a difference in degree.
- **Full stops stay soft boundaries** for transcripts with word timings. They are preferred split points for parts over the limits, not sentence ends that always start a new line.

## Other findings

- **Fist of Fury Gemini captures:** several chunks are unpunctuated rather than broken, and should be judged by repeated character n-grams, not repeated sentences. The third chunk of `fist_of_fury_gemini.json` (35:51–55:00) is a repetition loop. The first chunk of `fist_of_fury_gemini_presort_fix.json` holds 85 characters for 18 minutes. `fist_of_fury_gemini_first20.json` is too sparse to use.
- **Qwen late starts:** text before the first word the aligner matched should move the start earlier (`TranscriptCutter._fill_sparse_parts`), but here it does not move it far enough. This needs its own investigation.
- **The fixed word guards:** `_timing_words` drops words over 8× their estimate from timing, and `_capped_word` caps words at 4×. Both came in with cf51b22 for runaway spans seen in Gemini and Qwen, but apply to every provider, and the drop was not assessed separately from the cap.
- **Glued full stops:** Gemini writes `Ánimo.Nadie debía saber nada.` with no space at a speaker change. Treating a full stop followed by a capital as a sentence end was rejected, since it cannot be told apart from an acronym, a URL or a version number.

## Reproducing

```text
.\envsubtrans\Scripts\python.exe scripts/replay_transcription.py transcription_tests/la_madre_muerta_gemini.json --quiet --compare timing_correction_factor 0.0 0.6 0.7
```

The report counts lines shorter than their speech estimate, and flags each one `[fast]` without `--quiet`. The captures above predate recorded line settings, so they replay with the current options and each provider's defaults. See [transcription-tuning.md](transcription-tuning.md) for capturing and replaying transcriptions.
