# Transcription Providers: What We Know

This records what has been learned about each speech-to-text provider: what it returns, how it behaves on real media, and the choices the project made because of it. Most of it comes from development sessions in September and October 2026. Dates are given so that a finding can be checked or found to be out of date. Anything not confirmed from real output is marked as such.

How the project uses each provider (requests, parsing, retries) is documented in the provider and client code. This document covers the behaviour of the providers themselves.

## Summary

| Provider | Text | Punctuation | Word timings | Speakers |
|---|---|---|---|---|
| OpenRouter, MAI Transcribe 2 | Segments plus words | Yes, also as separate timed tokens | Yes, accurate | Yes, with diarization |
| OpenRouter, ElevenLabs Scribe v2 | Transcript plus words | Yes, attached to words | Yes, short words clipped | Yes, with diarization |
| ElevenLabs Scribe v2 (direct) | Transcript plus words | Yes, attached to words | Yes, short words clipped | Yes, with diarization |
| Gemini 3.5 Transcribe | Transcript plus words | Varies, absent in some captures | Yes | Yes, with diarization, verbatim mode only |
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

**ElevenLabs Scribe v2.** `elevenlabs/scribe-v2` was added to OpenRouter in October 2026. It was compared with MAI on Damo s01e06 (Korean, 62 minutes, with Jeolla dialect), in `test_transcriptions/damo/`.
- *Output.* One segment spanning the whole chunk, including silence, and a list of timed words with punctuation attached. Language is an ISO 639-3 code (`kor`).
- *Diarization.* Requested with `{'elevenlabs': {'diarize': True}}` under `provider.options`. Words carry numeric speaker IDs. It split lines at speaker changes that MAI merged, e.g. `아니라.` / `나가 간다고…` at 53:18.
- *Audio events.* Tagged inline by default, e.g. `[웃음]` and `[배경 음악]`. The client sends `tag_audio_events: false` unless the `audio_events` option is on, and OpenRouter passes it through. With tags on, each event is a single timed word, and 47 lines contained one, mostly at the start or end of a line of dialogue, in closed-caption style. Six lines were tags alone, capped at the 4 s line limit. Event timings span the sound, from 0.02 s up to 89 s for music under dialogue.
- *Zero-length words.* Some words have the same start and end. The client dropped them until October 2026. In the Damo capture, two chunks' words then covered 97% and 81% of their transcript.
- *Accuracy.* Spoken characters per 5-minute window match MAI within a few percent, with nothing missing. Each model has errors the other avoids. Scribe handled the dialect better (`성님`, `당겨불랑게`, `강녕하셨습니까`); MAI got some phrases Scribe misheard (`나서는` as `따서는`).
- *Timing.* Starts agree with MAI to about 0.1 s. Short words are clipped: 315 of 2,808 words last 60 ms or less, against 31 for MAI, e.g. `예.` in 20 ms. Lines are shorter for their text, with a median of 0.76 of the speech estimate against 0.84, and 28 lines below 0.5 against 2. The OpenRouter defaults are tuned for MAI, so no timing correction is applied.
- *Language hint.* The captures above used a `Korean` hint. A full transcription and translation of the same episode in the GUI, with no hint, looked excellent when watched.
- *Cost.* $0.11 for the episode at a 50% launch discount, against $0.10 for MAI. The list price is $0.22 per hour.

**Account restrictions.** Requests can fail with a 404 citing zero available endpoints when the account or workspace has zero-data-retention guardrails that exclude the model's providers.

## ElevenLabs

**Interface.** `POST /v1/speech-to-text` with a multipart upload and an `xi-api-key` header. The official SDK was not used: it installs about 31 MB, of which speech-to-text is under 1%, and the request is a single multipart POST.

**What it returns.** A transcript, an ISO 639-3 language code, the audio duration, a `transcription_id`, and typed words: `word`, `spacing`, and `audio_event` when events are tagged. Words carry speaker IDs such as `speaker_0`. There are no segments. Some words have zero length.

**Whole clips.** Damo s01e06 (62 minutes) was sent as one 127 MB FLAC upload in October 2026, and came back in 52 seconds. The 20 speaker IDs were consistent across the episode: the bandit who says `성님` is `speaker_11` at 19 and 51–53 minutes. Dialogue matched the chunked OpenRouter run almost exactly. An insert song at 58:40–60:15 was not transcribed, where MAI transcribed the lyrics.

**No early return without a webhook.** `webhook=true` returns at once and delivers the result later, but only to a webhook configured on the account. Without one the request is refused. A transcript can be fetched by `transcription_id`, but that ID only arrives with the result.

**Credits.** On a credit plan, transcription used about 67 credits per minute of audio: 4,194 for the 62-minute episode.

The model's accuracy and timing are described under OpenRouter, ElevenLabs Scribe v2.

## Gemini

**Interface.** Gemini 3.5 Transcribe through the Interactions API, with the audio uploaded through the Files API. There is no prompt. The request is a `transcription_config` with a mode, the timestamp granularity, diarization and optional language codes. The project uses `verbatim` mode, because speaker labels are only returned in that mode. What the other modes return was not recorded beyond that.

**What it returns.** A transcript, and word annotations with offsets and speaker labels. There is no detected-language field. The word annotations can leave out characters that are in the transcript, so the transcript is used for text and the words only for timing. Using the transcript recovered about 250 characters in one comparison, including negations.

**Word timings cover the transcript.** In the October 2026 captures of Fist of Fury and La Madre Muerta, and the September capture of Natural City, the words match the transcript almost entirely (median similarity 1.00). Many words have zero duration: 9% in the Fist of Fury capture and 5% in La Madre Muerta. These still have a usable start time.

Until 24 September 2026 the client dropped zero-duration words, so captures made before then have none. Their word timings look partial (similarity 0.92–0.99), and replays of them do not reflect current output. This applies to `fist_of_fury_gemini.json` and `la_madre_muerta_gemini.json`; the `_oct` captures replace them.

**Punctuation varies.** Spanish captures have full stops. Some Cantonese captures have no punctuation at all. In the Fist of Fury capture, the scene at 4:15–4:55 is one unpunctuated run, `…不是嘛朱姐啊朱姐朱姐你有我死了朱姐啊朱姐开门先啦…`, where MAI has `唔係嘛？姑姐啊！姑姐！`. Gemini also misheard `姑姐` ("Auntie") as `朱姐` throughout. Words are sometimes glued together with no space, often at a speaker change, as in `Ánimo.Nadie`.

**Silent omissions.** Gemini can leave out whole stretches of audio without any error or warning. Some 10–20 minute spans were 43–79% complete. The recommended maximum chunk length was cut from 20 to 15 minutes because of this, but a later test showed that chunk length only changes which stretches go missing. On one 20-minute passage, short chunks returned 760 characters and a long chunk 1,388, where MAI returned 4,262.

The same film transcribed again in October 2026 (`fist_of_fury_gemini_oct.json`) returned 7,727 spoken characters, where MAI returned 13,014. The first 10 minutes, most of 25–35 minutes and nearly all of 80–95 minutes are missing. The September capture of the same film was missing different stretches.

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

**Korean.** Korean alignment needs `soynlp`, which the local transcription setup installs with `qwen-asr`. In an environment prepared by hand without it, Korean is split on spaces instead of into morphemes, so the timings are coarser.

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
- **Zero-length words.** Gemini and ElevenLabs Scribe return words whose start and end are the same. Every client keeps them, since the start is still usable, and drops only words that end before they start.
- **Chunk lengths are project choices.** The defaults (Qwen Local 30–60 s, OpenAI and Muse 8–60 s, OpenRouter 30–120 s, chunked ElevenLabs 10–15 minutes, Gemini 10–15 minutes) were chosen by the project. ElevenLabs accepts files of up to 5 GB, and can send the whole clip in one request.
