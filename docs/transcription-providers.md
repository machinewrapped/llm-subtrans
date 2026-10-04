# Transcription Providers: What We Know

This records what has been learned about each speech-to-text provider: what it returns, how it behaves on real media, and the choices the project made because of it. Most of it comes from development sessions in September and October 2026. Dates are given so that a finding can be checked or found to be out of date. Anything not confirmed from real output is marked as such.

How the project uses each provider (requests, parsing, retries) is documented in the provider and client code. This document covers the behaviour of the providers themselves.

## Summary

| Provider | Text | Punctuation | Word timings | Speakers |
|---|---|---|---|---|
| OpenRouter, MAI Transcribe 2 | Segments plus words | Yes, also as separate timed tokens | Yes, accurate | Yes, with diarization |
| Gemini 3.5 Transcribe | Transcript plus words | Varies, absent in some captures | Partial | Yes, with diarization, verbatim mode only |
| Qwen Local | Transcript plus aligned words | In the transcript only | Partial, from a forced aligner | No |
| OpenAI `whisper-1` | Segments plus words | Not checked | Yes | No |
| OpenAI `gpt-4o-transcribe-diarize` | Segments | Not checked | No, segment timings only | Yes |
| Muse | Turns | Mostly | No, turn timings only | Yes, with diarization |

MAI Transcribe 2 has given the best results in this project's testing, and is the default OpenRouter model. Its output is the reference to check other providers against, e.g. `transcription_tests/fist_of_fury_openrouter_fixed.vtt`.

## OpenRouter

**Default model.** `microsoft/mai-transcribe-2` replaced `openai/whisper-large-v3` as the default in September 2026, because it gave the best results. Other models available through OpenRouter include Whisper variants, Qwen ASR, Google Chirp 3, Deepgram Nova 3 and Grok STT 1.0. Diarization support is per model. Deepgram Nova 3 and Grok STT 1.0 return speaker IDs, but their word timings have not been checked. The Whisper variants return no speaker IDs.

**What MAI returns.** Sentence-like segments, speaker-tagged when diarized, and a separate list of timed words. Punctuation is attached to the words, and is also returned as separate punctuation-only words with their own timings. A Fist of Fury capture has about 2,600 of these, including `，`, `。`, `？`, `！` and `-`. In that capture the `-` tokens are stutters (`你 - 你`), not dialogue openers.

**Segments can be long.** In a Korean capture, about half of 471 segments were over three seconds, and the longest was two minutes. Many contained several sentences. The pause after a full stop had a median of 0.96 s, against 0.18 s after a comma and 0.10 s between words.

**Timing.** Accurate enough that timing correction is left at 0. In one replay, a correction factor of 0.6 would have changed only 16 of 1,417 lines.

**Language hints.** A wrong hint degrades the output. On a 64-minute Korean episode, a `Chinese` hint put Chinese characters into 56 of 848 lines, and the correct `Korean` hint avoided it. Omit the hint when unsure.

**Duplicated output.** Rarely, MAI returns the same utterance twice at the same times, once in Traditional Cantonese and once in Simplified Mandarin. The cause is not known. Whether a `yue` or `zh-HK` hint prevents it has not been tested.

**Account restrictions.** Requests can fail with a 404 citing zero available endpoints when the account or workspace has zero-data-retention guardrails that exclude the model's providers.

## Gemini

**Interface.** Gemini 3.5 Transcribe through the Interactions API, with the audio uploaded through the Files API. There is no prompt. The request is a `transcription_config` with a mode, the timestamp granularity, diarization and optional language codes. The project uses `verbatim` mode, because speaker labels are only returned in that mode. What the other modes return was not recorded beyond that.

**What it returns.** A transcript, and word annotations with offsets and speaker labels. There is no detected-language field. The word annotations can leave out characters that are in the transcript, so the transcript is used for text and the words only for timing. Using the transcript recovered about 250 characters in one comparison, including negations.

**Word timings are partial.** They can miss stretches of the transcript. About 6% of the words in one film capture had zero duration. These still have a usable start time.

**Punctuation varies.** Spanish captures have full stops. Some Cantonese captures have no punctuation at all. In the Fist of Fury capture, the scene at 4:15–4:55 is one unpunctuated run, `…不是嘛朱姐啊朱姐朱姐你有我死了朱姐啊朱姐开门先啦…`, where MAI has `唔係嘛？姑姐啊！姑姐！`. Gemini also misheard `姑姐` ("Auntie") as `朱姐` throughout. Words are sometimes glued together with no space, often at a speaker change, as in `Ánimo.Nadie`.

**Silent omissions.** Gemini can leave out whole stretches of audio without any error or warning. Some 10–20 minute spans were 43–79% complete. The recommended maximum chunk length was cut from 20 to 15 minutes because of this, but a later test showed that chunk length only changes which stretches go missing. On one 20-minute passage, short chunks returned 760 characters and a long chunk 1,388, where MAI returned 4,262.

**Degenerate output.** Seen in real captures:
- A chunk of about 7 minutes returned no text or words, and reported success.
- Repetition loops. The third chunk of `fist_of_fury_gemini.json` (35:51–55:00) repeats the same short lines dozens of times.
- Latin-script text leaking into non-Latin transcripts, and duplicated blocks.

A safety filter was suggested as a cause, but the raw responses showed no safety signal.

**Diarization.** One speaker label was given to a four-line exchange that the reference shows is two speakers.

**Language hints.** BCP-47 codes, with no published list or validation in the SDK. The hint is not a whitelist: codes outside Gemini's published table of 85 are accepted, and the model still detects the language. Whether an unlisted language such as Welsh is handled well has not been tested.

## Qwen Local

**Models.** `Qwen/Qwen3-ASR-1.7B` by default, or `Qwen/Qwen3-ASR-0.6B`, with `Qwen/Qwen3-ForcedAligner-0.6B` for word timings. The models are about 6.1 GB in total, downloaded to the Hugging Face cache on first use.

**What it returns.** A transcript and a detected language from the ASR model, and word timings from the aligner. There are no speaker labels, and no punctuation in the words.

**Word timings are partial.** The aligner can leave out stretches of the transcript, cram runs of words into a few milliseconds, or give a single character several seconds. The word list alone loses about 28% of the characters and all punctuation, so the transcript is used for text.

**Aligner drift.** Under loud background noise the aligner can lose its place and time the following words seconds late. See [#504](https://github.com/machinewrapped/llm-subtrans/issues/504) for an example at 13:43 in Fist of Fury, where words run about 2 to 2.5 s late under a ringing phone.

**Languages.** 30 supported languages. A hint for an unsupported language logs a warning and falls back to auto-detection. The model does not translate. In `qwen-asr` 0.0.6, the aligner does not reject unsupported languages.

**Korean.** Korean alignment needs `soynlp`, which the packaged app leaves out because it is GPL-licensed. Without it, Korean is split on spaces instead of into morphemes, so the timings are coarser.

**Speed.** About 18 s per 30-second chunk with the 1.7B model and aligner on one CUDA machine, at about 33% GPU utilisation. That is roughly ten times slower than MAI.

## OpenAI

**Models.** `whisper-1` returns segments and word timings through `verbose_json`, with no speaker labels. `gpt-4o-transcribe-diarize` returns speaker-tagged segments through `diarized_json`, with no word timings. `gpt-4o-transcribe` and `gpt-4o-mini-transcribe` return no timings, so they cannot be used for subtitles.

**Language hints.** `whisper-1` takes an ISO-639-1 code.

**Empty audio.** Music or noise gives a successful empty response.

No OpenAI transcription has been assessed on real media yet.

## Muse

**What it returns.** `muse-voice-transcribe-1.0` returns turns, each with text, a speaker label and start and end offsets in milliseconds. There are no word timings. The request always asks for diarization.

**Long turns.** In one 919-turn capture, over 100 turns were longer than six seconds and the longest was 78 seconds. Long turns sometimes have speech at both ends with silence in between. Seven turns had zero length.

**Punctuation.** Mostly punctuated. In the Fist of Fury capture, 665 of 914 turns end in punctuation, and 72 turns of more than 8 characters have none. Cantonese is punctuated with full-width marks, mixed with some half-width `,` and `?`. About one full-width mark in nine is followed by a space, as in `阿正， 你唔好强颜欢笑啦`.

**Language.** The language field is free text.

## Across providers

- **Punctuation tokens.** Of the providers with captures, only MAI returns punctuation as separate timed words. Gemini and Qwen return none.
- **Empty audio.** Music or noise returns a successful empty result from all the API providers.
- **Chunk lengths are project choices.** The defaults (Qwen Local 30–60 s, OpenAI and Muse 8–60 s, OpenRouter 30–120 s, Gemini 10–15 minutes) were chosen by the project. No provider-published limits are recorded.
