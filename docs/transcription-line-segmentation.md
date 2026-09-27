# Transcription Line Segmentation

Transcribed Korean runs to lines too long to read, and the translation inherits them, because each source cue becomes one translated cue (#477). This document covers how lines were built, the levers tried and what they showed, and the change made: every sentence end, full stops included, now starts a new line.

The evidence comes from MAI Transcribe 2 and Gemini captures, replayed against the line builder with prototype variants patched in, and judged blind by Codex (`gpt-6-luna`).

## Principles

- **The transcription is a source for translation.** Each cue becomes one translated cue with the same timing. Source-language reading limits, such as Korean characters per row, do not carry over to the translation. Line length is judged by speaking time instead, which suggests how much text any translation will need.
- **MAI is the best case.** Its transcripts are complete and accurate, with speaker labels, punctuation and word timings. Other providers miss words, time them less reliably, or glue sentences together. A design tuned on MAI must hold up on them too.
- **Complete sentences stay separate.** A sentence with a comfortable reading time keeps its own cue. Sentence ends are the preferred place to break a line.
- **Extending beats merging.** A brief line is better extended into the pause after it than merged with a neighbour. Reading time depends on the target language, so extension belongs at save time, where `extend_short_subtitles` already does it, not in the transcription.
- **Speech, not characters per second.** Lines are judged by estimated speaking time (`EstimateSpeechSeconds`), which allows for the script.

## How lines were built

For a provider with its own segments and word timings, such as MAI, each audio chunk goes through three steps in `TranscriptionLineBuilder`.

1. **Keep or split each provider segment.** A segment (a "part") that fits within `max_line_duration` and `max_characters` (120) becomes one line as it is. One that exceeds either is split by `UtteranceSplitter.FitUtterance`, recursively, at the highest-scoring word gap until every piece fits. A gap scores by its pause, weighted towards the middle of the segment, plus a bonus for the punctuation before it. `?`, `!` and `。` get the sentence bonus (0.5), while `.` gets only the clause bonus (0.15), the same as `,`.
2. **Merge lines too brief to read.** `LineMerger.MergeSlivers` treats a line under `min_line_duration` (0.8 s) as a sliver. A sliver joins the line after it, whatever that line's length, unless it can be extended into a pause instead. The two lines must be close enough (0.5 s, or 1.0 s for the same speaker), and different speakers become a dialogue cue (`- a` / `- b`). A merged run is divided evenly if it breaks the limits. Slivers do not join the line before them: when they did, runs of them stacked into long, dense lines.
3. **Extend brief lines.** `_extend_into_pauses` extends a sliver to `min_line_duration` where the pause after it allows. With a per-provider `timing_correction_factor` above zero, a line too short for its text is also extended towards its estimated speaking time. MAI has it at 0, since its timings are accurate.

At save time, `extend_short_subtitles` extends each translated line into the gap after it, up to `max(min_line_duration, characters × seconds_per_character)` of the target text.

What this meant for Korean from MAI:

- **A sentence end inside a segment never started a line.** MAI's segments are paragraphs (see below), so several sentences shared a line until the segment broke a limit.
- **Korean got no sentence ends.** Chinese and Japanese end sentences with `。`, which scores as a sentence end when splitting. Korean uses `.`, which scored like a comma.
- **Only the duration cap limited length.** 120 characters is about 2.5 times the longest Korean line the duration cap let through.

## The change

Every word that ends a sentence now ends a line, whether or not the segment is over a limit.

- **`EndsSentence` (`Speech.py`)** says whether a word, with its punctuation, ends a sentence: `?`, `!`, `。`, ellipses, and full stops other than after initials or dotted abbreviations. It looks past closing quotes and brackets.
- **`UtteranceSplitter.SplitSentences`** cuts a segment's words after each such word, and `TranscriptionLineBuilder._fit_part` fits each sentence to the limits as before. `IsHardBoundary`, used where lines are built from words alone, and the split scoring use the same test.
- **Transcripts are cut into parts at every sentence end too** (`TranscriptCutter`, using `TimedSentenceRanges`). Gemini often writes sentences with no space after the full stop: 140 times in La Madre, as in `dinero.Adelante.Hola`. `IsSentenceEnd` cannot tell those from abbreviations by the text alone, so a full stop with a timed word starting straight after it also ends a sentence. 138 of the 140 are recognised; the other two have no timed word after them.
- **Why the glued case matters.** Gemini gave `Ánimo` in `…Tú te la llevas. Ánimo.Nadie debía saber nada.` no word timing. Untimed text at the start of a part takes its timing and speaker from the words after it, so cutting at full stops without the glued rule moved `Ánimo.` 22 s later, to the next speaker. MAI heard it 2 s after `llevas.`, from the same speaker. Recognising the glued full stop makes `Ánimo.` a sentence of its own, placed at the start of the pause like other untimed parts. Before this change the cutter cut only at strong ends, and got `Ánimo` right only because its range happened to start at the previous speaker's words. Of 17 untimed stretches in La Madre, only three sit in a real pause; the other two, both `Qué` opening a sentence, belong with the words after them, as placed.
- **Two fixes to `IsSentenceEnd`** came out of the replay. A single syllabic character before a full stop, such as Korean `중.` or `봐.`, counted as an initial like `J.`; and three typed full stops counted as a dotted abbreviation rather than an ellipsis. Both now end a sentence. The prototypes had both faults, so the change splits Korean slightly more than the assessed versions: 1,026 cues against 1,017 on Natural City at 5 s. Other captures replay identically to the prototype.

`LineMerger` and save-time extension are unchanged, and apply to the new lines as before.

## Levers tried

"Current code" here and in the evidence below means the code before this change. Replayed on Natural City at `max_line_duration` 5 s, the setting the reported file used. Lines over 32 characters exceed the Korean guidance of about 16 characters per row, over two rows.

| Lever | Kind | What it changes | Result |
|---|---|---|---|
| Current code | | | 921 cues, 162 of 1 s or less, 79 over 32 characters |
| `max_line_duration` 4 s | existing setting | Tighter duration cap | 52 over 32 characters, but forced cuts at shorter durations read unnaturally |
| `timing_correction_factor` | existing setting | Extends lines towards their source-language speaking time | Off for MAI by design. It times lines by the source language, which may not suit the target, and save-time extension already handles the target. |
| `extend_short_subtitles` | existing setting | Extends translated lines by target text length | Used on the reported translation: 114 English cues end later than their Korean source. Cues of 1 s or less fell from 144 to 120, since short target text rightly stays short. |
| Script-scaled character cap (#477 as filed) | prototype | `max_characters` scaled by the text's seconds per character, about 42 Korean syllables | No change: the duration cap bites first |
| Full stops as forced breaks | prototype | Every sentence end inside a segment starts a line | 1,017 cues, 277 of 1 s or less, 71 over 32. Lost blind round 13. |
| Speech-estimate cap | prototype | A line must fit `max_line_duration` by its speech estimate as well as its duration | With forced breaks: 30 over 32, 280 of 1 s or less. Lost round 14. |
| Sentence packing | prototype | Split at sentence ends, then rejoin sentences in order while they fit | 926 cues, 79 over 32: moves breaks, barely shortens lines. With the speech-estimate cap: 963 cues, 163 of 1 s or less, 39 over 32. Narrowly lost round 15. |
| Comfortable display time | prototype, dropped | Extends brief lines to 1.5 s in the transcription | Cues of 1 s or less fell from 162 to 32. Dropped: it duplicates save-time extension, in the source language. |

Packing fills each line in order until the next sentence will not fit, so lines drift towards the limit in whole sentences. That goes against keeping complete sentences separate, so packing is not a direction to pursue.

## Evidence

Captures: `transcription_tests/natural_city_openrouter.json` (no diarization) and `natural_city_openrouter_diarized.json`. Figures use the diarized capture. `main` at 5 s reproduces the reported file exactly: 830 lines against 828, with identical cues at 21:22.

### What MAI returns

- **Segments are paragraphs.** Of 475 segments, half run over 3 s, 1 in 10 over 20 s, and the longest two minutes. 204 contain an internal `. `, and 78 an internal `?` or `!`.
- **Segments break at speaker changes.** 388 of 407 boundaries between segments are speaker changes, and only 8 are the same speaker less than a second apart. Cantonese from MAI has 98 of those, out of 1,124.
- **Words are space-delimited, with punctuation attached.** Only 11 of 4,085 words are punctuation on their own.
- **Pauses mark sentence ends.** Gaps between one speaker's words:

| After | Gaps | p10 | Median | p90 | Share at least 0.3 s |
|---|---|---|---|---|---|
| `.` | 459 | 0.20 | 0.96 | 6.80 | 84% |
| `?` / `!` | 127 | 0.24 | 1.10 | 5.76 | 86% |
| `,` | 184 | 0.02 | 0.18 | 0.80 | 39% |
| other words | 2,833 | 0.04 | 0.10 | 0.28 | 10% |

### Other languages

The same prototypes at the default 4 s:

| Capture | Variant | Cues | 1 s or less | Over limit |
|---|---|---|---|---|
| La Madre Muerta, Gemini (Spanish, over 84 chars) | Current code | 518 | 217 | 4 |
| | Full stops as forced breaks | 605 | 314 | 3 |
| | Packing + speech-estimate cap | 526 | 213 | 1 |
| Fist of Fury, MAI (Cantonese, over 32 chars) | Current code | 1,417 | 361 | 6 |
| | Full stops as forced breaks | 1,502 | 464 | 7 |
| | Packing + speech-estimate cap | 1,462 | 369 | 7 |

Forced breaks at every full stop add about 100 brief cues in each language.

### Blind assessment

Codex (`gpt-6-luna`) compared two 25-minute windows (minutes 8-33 and 65-90) at 5 s, without the key. Files are in `transcription_tests/assess/round13` to `round15`, with keys alongside the folders. Rounds 13 to 16 preferred the current code, with medium confidence, but the prompts for rounds 13 to 15 had flaws that undermine their verdicts (see below). Round 17 preferred full stops.

- **Round 13, forced breaks at full stops:** objected to brief cues, 49 against 79 and 54 against 86 at 1 s or less, such as `선배.` and `친구 없죠?` at 0.8 s each.
- **Round 14, forced breaks with the speech-estimate cap:** objected to cuts inside sentences, such as `4명의 폭주 사이보그가` / `인간의 DNA가 저장된…`. The cap also stranded `네.` for 0.24 s by blocking a merge.
- **Round 15, packing with the speech-estimate cap:** a slight edge. Packing won each break it made at a sentence end, but lost on cuts inside sentences, worst after a modifier before its noun: `폐수처리장으로 연결되는` / `M323 구역으로 진입.`

Every round named long cues as the biggest problem in the version it preferred. Breaks at sentence ends were judged better each time. Forced breaks after every sentence, and cuts inside a sentence, were judged worse.

These rounds have limits:

- **Rounds 13 and 14 were told something false.** Their prompts said each cue is translated separately. llm-subtrans translates in batches with context, and the claim steered the assessor towards whole sentences.
- **No round was told about save-time extension.** Brief cues were judged as they would never be shown. `선배.` (said in 0.60 s) and `친구 없죠?` (0.84 s) have 2 s of silence between them to extend into. The current code's `선배. 친구 없죠?` shows the second sentence 2 s before it is said, which the assessor did not flag.
- **Every prompt set a source-language yardstick:** about 16 Korean characters per row, a limit that does not carry over to the translation.
- **The assessor is a model.** It never went above medium confidence.

The rounds should be rerun with a neutral prompt before their verdicts are relied on.

- **Round 16, forced breaks at full stops, neutral prompt:** both files replayed with `timing_correction_factor` 0.7 as a stand-in for save-time extension. The prompt gave only the task and asked which version makes better subtitles for a viewer. The current code was preferred in both windows, with medium confidence. The objection was short sentences shown for about 0.8 s, such as `현재 준비.`, `이봐, 친구.` and `선배!`. Full stops won where they separate a question from its answer or a follow-up, such as `알겠나?` / `네!` and `왜? 일진이 안 좋아?` / `변태라도 걸렸어?`.

Most of these brief cues have a pause after them. With full stops, 204 of the 267 cues of 1 s or less have room to be shown for 1.5 s, and only 36 are followed by the next cue within 0.3 s. They stay at the 0.8 s floor because the speech estimate for a short sentence is under 0.8 s, so timing correction adds nothing, and save-time extension has the same floor. 0.8 s is close to Netflix's recommended minimum display time of 5/6 s, so these cues are within standard practice; the assessor simply prefers longer ones. Round 17 tested whether that was the only objection.

- **Round 17, forced breaks at full stops, with a 1.2 s floor:** both files as in round 16, with every cue extended to 1.2 s where the gap to the next cue allows. Cues of 1 s or less fell to 32 (current code) and 41 (full stops). **Full stops were preferred in both windows,** with medium confidence. They won by separating an instruction from its confirmation (`탐지 모드 전환` / `전환`, 11:09), a question from its answer (`야, 그럼 지로는 뭐야?` / `죽었잖아.`, 1:12:06), and a panicked instruction into beats. The current code was better for short beats that belong together, such as `선배. 친구 없죠?` and the repeated `어?` tags at 31:40. It was also better at the rapid callouts at 1:26:53, where the merger stacked three distance calls and a report into one dialogue cue.

The 1.2 s floor, like factor 0.7, is an evaluation device only. It removes the assessor's preference for longer cues, which 0.8 s already satisfies in standard practice. It is not a change to ship: `min_line_duration` keeps its meaning, shared with the preprocessor.

With enough display time, breaks at full stops are preferred. What remains is deciding when short sentences belong together, and stopping the merger from stacking brief lines. Full stops alone do not fix length: 70 cues still run over 32 characters, against 78.

### Site-by-site assessment

Rounds 18 to 20 judged every place where the two versions differ, rather than whole windows. Both versions were replayed with the round 17 evaluation adjustments (factor 0.7 and the 1.2 s floor). Each site showed the two versions as X and Y, in random order per site, and the assessor chose X, Y or same for someone watching the film. Files are in `transcription_tests/assess/round18`, `round19_*` and `round20_*`, with keys and site features alongside.

| Capture | Sites | Sentence ends preferred | Current code preferred | High confidence |
|---|---|---|---|---|
| Natural City (MAI, Korean) | 128 | 97 | 31 | 68 to 7 |
| Natural City (Gemini, Korean) | 125 | 108 | 17 | 80 to 6 |
| Fist of Fury (MAI, Cantonese) | 130 | 113 | 17 | 101 to 6 |
| La Madre Muerta (Gemini, Spanish) | 105 | 77 | 28 | 55 to 4 |

Fist of Fury from Gemini, Qwen Local and Muse does not change: their segments are already cut at sentence ends. Natural City from Gemini (round 20) was replayed against `main` and the branch with the same evaluation adjustments. Gemini transcribed about 18% less text than MAI, leaving several minutes untranscribed at the start and end of the film, but timed every word it wrote; it glued 278 sentences together without a space, of which 276 are recognised. Most of its 17 losses are knock-on cuts where a glued sentence runs into the next part, such as `나도` and `현재 MP 위치는` left dangling. Gemini's glued `Ánimo.Nadie` failure does not recur (see The change).

No feature of the timing predicts which breaks lose. On Natural City, sentence ends won 74-83% of breaks whether the pause was short or long, whatever each sentence's spoken length, after `.` or `?`/`!`, and even when one side was two syllables or fewer. Packing consecutive sentences up to a duration would rejoin about two breaks the assessor preferred for each one it did not, at any limit from 2 to 3 s. The losses are judgements about meaning, such as a follow-up or an insult that belongs with the sentence before it (`넌 이용당한 거야. 병신 같은 새끼야.`, `Queremos 20 millones. ¿Ha oído?`).

The one structural weakness is in `LineMerger`: after the split, brief lines are stacked into dialogue cues of three or more turns (Natural City sites 27 and 118, Fist of Fury sites 17, 22, 33, 82 and 114).

### Speaking rates

Seconds per spoken character, over runs of one speaker's words with no gap over 0.3 s:

| Capture | Runs | p25 | Median | p75 |
|---|---|---|---|---|
| Natural City, MAI (Korean) | 742 | 0.124 | 0.143 | 0.165 |
| Fist of Fury, MAI (Cantonese) | 898 | 0.130 | 0.145 | 0.163 |
| Fist of Fury, Gemini (Cantonese) | 805 | 0.133 | 0.156 | 0.175 |
| Fist of Fury, Qwen Local (Cantonese) | 596 | 0.147 | 0.183 | 0.229 |
| La Madre Muerta, Gemini (Spanish) | 555 | 0.052 | 0.060 | 0.071 |

Korean and Cantonese are spoken at the same syllable rate. The constants in `Speech.py`, 0.2 s per syllabic character and 0.07 s for others, were measured over whole segments, so they fold in pauses: about 40% extra for syllabic scripts and 17% for Spanish.

## Evaluation

- **Acceptance:** better results on Natural City without significant regressions on the other captures.
- **Captures:** Natural City (MAI, with and without diarization), Fist of Fury (MAI, Gemini, Qwen Local, Muse), and La Madre Muerta (Gemini).
- **No translation:** the target language is unknown, so the source is judged. Both versions get the same evaluation adjustments: `timing_correction_factor` 0.7 and a 1.2 s display floor where the gap allows, standing in for save-time extension and removing the assessor's preference for longer cues.
- **Neutral prompts:** the assessor is told only that the words are identical and the cue boundaries differ, and asked which version makes better subtitles for someone watching the film. It is not given criteria, reading limits, or claims about how the cues are used.
- **Site by site:** judging each place the versions differ, rather than whole windows, shows which breaks win and lose, and gives enough verdicts to test features against.

## Follow-ups

- **Merger stacking.** `LineMerger` stacks brief lines into dialogue cues of three or more turns. One option is to fold one speaker's consecutive turns into a single row, such as `- 280m. 270m.` / `- 다가오고 있다.` for the callouts at 1:26:53, though that reorders the speech.
- **Long lines.** Sentence ends do not shorten long single sentences: 70 cues on Natural City still run over 32 characters, against 78. The speech-estimate cap shortened them but lost on its cuts inside sentences, worst after a Korean modifier ending (`-는`, `-인`) before its noun.
- **Speech estimate.** `EstimateSpeechSeconds` could be re-derived as speaking rate plus pauses, with rates measured per script (see Speaking rates). Timing correction and the replay report are calibrated on the current constants.

## Alternatives not pursued

- **Scored segmentation.** Choosing the lowest-cost division of each stretch of speech, with costs for duration, brevity, reading load and each break's pause and punctuation, found by dynamic programming. The site-by-site results showed no timing or length feature that predicts which sentence breaks lose, so costs built from those features would have no more to go on than a simple rule. It may still be the right tool for long lines, where the trade-off is between reading load and where a sentence can be cut.
- **Sentence packing** and the **script-scaled character cap**: see Levers tried.
