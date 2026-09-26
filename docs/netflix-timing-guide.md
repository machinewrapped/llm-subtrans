# Netflix Timing Guide

This is a reference for the `use_netflix_timing_guide` setting, which extends short subtitles when a translation is saved.
It records the reading speeds, counting rules and timing rules from Netflix's [Timed Text Style Guides](https://partnerhelp.netflixstudios.com/hc/en-us/sections/22463232153235-Timed-Text-Style-Guides), as retrieved on 26 September 2026.
Netflix updates the guides from time to time, so check the source before relying on a figure.

The implementation is in `PySubtrans/Helpers/Reading.py` (reading speeds and counting) and `Subtitles._apply_netflix_timing` (timing rules).

## Reading speed limits

Limits are in characters per second.
LLM-Subtrans uses the adult limit for interlingual subtitles.
Afrikaans and Zulu allow a higher limit for SDH (subtitles for the deaf and hard of hearing), which does not apply to translations.
The Japanese guide gives a single limit for subtitles, without separate adult and children's figures, and a separate limit of 7 for Japanese SDH.

| Language | Adult | Children | Style guide |
|---|---|---|---|
| Afrikaans | 17 (SDH: 20) | 17 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/47532730483347-Afrikaans-Timed-Text-Style-Guide) |
| Arabic | 20 | 17 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215517947-Arabic-Timed-Text-Style-Guide) |
| Bangla | 22 | 18 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/4483351778963-Bangla-Timed-Text-Style-Guide) |
| Basque | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/5521178339731-Basque-Timed-Text-Style-Guide) |
| Bulgarian | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/115002941367-Bulgarian-Timed-Text-Style-Guide) |
| Catalan | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/5519503237779-Catalan-Timed-Text-Style-Guide) |
| Chinese (Simplified) | 9 | 7 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215986007-Chinese-Simplified-Timed-Text-Style-Guide) |
| Chinese (Traditional) | 9 | 7 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215994807-Chinese-Traditional-Timed-Text-Style-Guide) |
| Croatian | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/115002790368-Croatian-Timed-Text-Style-Guide) |
| Czech | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/115002884887-Czech-Timed-Text-Style-Guide) |
| Danish | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/216014347-Danish-Timed-Text-Style-Guide) |
| Dutch | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215350158-Dutch-Timed-Text-Style-Guide) |
| English (UK) | 20 | 17 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/30806198616339-English-UK-Timed-Text-Style-Guide) |
| English (USA) | 20 | 17 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-English-USA-Timed-Text-Style-Guide) |
| Filipino | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/4480978897939-Filipino-Timed-Text-Style-Guide) |
| Finnish | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215087558-Finnish-Timed-Text-Style-Guide) |
| French (Canada) | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/42738240066835-French-Canada-Timed-Text-Style-Guide) |
| French (France) | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/217351577-French-France-Timed-Text-Style-Guide) |
| Galician | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/5517261090451-Galician-Timed-Text-Style-Guide) |
| German | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/217351587-German-Timed-Text-Style-Guide) |
| Greek | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/235511047-Greek-Timed-Text-Style-Guide) |
| Hebrew | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/220636427-Hebrew-Timed-Text-Style-Guide) |
| Hindi | 22 | 18 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/115003196707-Hindi-Timed-Text-Style-Guide) |
| Hungarian | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/115003064248-Hungarian-Timed-Text-Style-Guide) |
| Icelandic | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/360063377373-Icelandic-Timed-Text-Style-Guide) |
| Indonesian | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/216009727-Indonesian-Timed-Text-Style-Guide) |
| Irish | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/43418149359507-Irish-Timed-Text-Style-Guide) |
| Italian | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215349898-Italian-Timed-Text-Style-Guide) |
| Japanese | 4 (SDH: 7) | Not specified | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215767517-Japanese-Timed-Text-Style-Guide) |
| Kannada | 22 | 18 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/4482685308819-Kannada-Timed-Text-Style-Guide) |
| Korean | 12 | 9 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/216001127-Korean-Timed-Text-Style-Guide) |
| Malay | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/115002675707-Malay-Timed-Text-Style-Guide) |
| Malayalam | 22 | 18 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/4482522640275-Malayalam-Timed-Text-Style-Guide) |
| Marathi | 22 | 18 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/4483518309907-Marathi-Timed-Text-Style-Guide) |
| Norwegian | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/216015647-Norwegian-Timed-Text-Style-Guide) |
| Polish | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/216787928-Polish-Timed-Text-Style-Guide) |
| Portuguese (Brazil) | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215600497-Portuguese-Brazil-Timed-Text-Style-Guide) |
| Portuguese (EMEA) | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/216787938-Portuguese-EMEA-Timed-Text-Style-Guide) |
| Romanian | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/220294068-Romanian-Timed-Text-Style-Guide) |
| Russian | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215346638-Russian-Timed-Text-Style-Guide) |
| Sámi (Northern) | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/26676366377747-S%C3%A1mi-Northern-Timed-Text-Style-Guide) |
| Serbian | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/115002813348-Serbian-Timed-Text-Style-Guide) |
| Slovak | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/115002812588-Slovak-Timed-Text-Style-Guide) |
| Spanish (Latin America & Spain) | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/217349997-Spanish-Latin-America-Spain-Timed-Text-Style-Guide) |
| Swedish | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/216014517-Swedish-Timed-Text-Style-Guide) |
| Tamil | 22 | 18 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/4481912003987-Tamil-Timed-Text-Style-Guide) |
| Telugu | 22 | 18 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/4482320288787-Telugu-Timed-Text-Style-Guide) |
| Thai | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/220448308-Thai-Timed-Text-Style-Guide) |
| Turkish | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215342858-Turkish-Timed-Text-Style-Guide) |
| Ukrainian | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/115002229068-Ukrainian-Timed-Text-Style-Guide) |
| Vietnamese | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/220447048-Vietnamese-Timed-Text-Style-Guide) |
| Welsh | 17 | 13 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/4490075626771-Welsh-Timed-Text-Style-Guide) |
| Zulu | 17 (SDH: 20) | 17 | [Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/40460648109715-Zulu-Timed-Text-Style-Guide) |

In summary:

| Adult limit | Languages |
|---|---|
| 22 | Bangla, Hindi, Kannada, Malayalam, Marathi, Tamil, Telugu |
| 20 | English, Arabic |
| 17 | All other languages with a guide, and the default for languages without one |
| 12 | Korean |
| 9 | Chinese (Simplified and Traditional) |
| 4 | Japanese |

## Counting rules

From [How is reading speed measured? Do punctuation and spaces count?](https://partnerhelp.netflixstudios.com/hc/en-us/articles/115001352212-How-is-reading-speed-measured-Do-punctuation-and-spaces-count):

> Spaces and punctuation are counted by the software towards both the character count and the reading speed limit.
> For single-byte (half width) characters for character-based languages, punctuation and Latin characters count as 0.5 character, unless specified otherwise in the language Style Guide.

The language guides add:

- **Japanese**: "Full-width character, space, and punctuation counts as 1 character. Half-width character, space, and punctuation counts as 0.5 characters."
- **Korean**: "Latin characters, spaces, punctuation count as 0.5 character."
- **Thai**: "35 characters per line (excluding all composite characters, i.e. tone marks, top and bottom vowels are not counted)."
- **Japanese ruby** (furigana) is drawn above or beside its base characters rather than inline, so it is not part of the line.
  SRT files cannot represent ruby, so conversions often insert the reading after its kanji, e.g. "美津子みつこ", which inflates the count.

## Timing rules

From [General Requirements](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617-Timed-Text-Style-Guide-General-Requirements) and [Subtitle Timing Guidelines](https://partnerhelp.netflixstudios.com/hc/en-us/articles/360051554394-Timed-Text-Style-Guide-Subtitle-Timing-Guidelines):

- **Minimum duration**: 5/6 of a second per subtitle event (20 frames at 24 fps).
  The Japanese guide sets its own minimum of 0.5 seconds.
- **Maximum duration**: 7 seconds per subtitle event.
- **Gaps**: subtitles must have a minimum of 2 frames between them.
  In 24 fps content, gaps of 3 to 11 frames inclusive must be closed to 2 frames, so every gap is either 2 frames or half a second or more.
  Gaps are closed by extending the out-time of the previous subtitle.
- **Frame rates**: the guidelines are written for 24 fps, where half a second is 12 frames.
  For higher frame rates the half-second rule still applies, e.g. 15 frames at 30 fps.
- **Shot changes**: in-times and out-times are snapped to shot changes within half a second, keeping a 2-frame gap from the cut.

## How LLM-Subtrans applies them

- The reading speed comes from the project's target language.
  Regional variants such as "French (Canada)" share their base language's limit, so only the language code matters.
  When the target language is not recognised, the language is detected from the script of each subtitle, and anything unrecognised uses 17.
- Characters are counted as above: spaces and punctuation count, half-width characters count as 0.5 in Chinese, Japanese and Korean, and Thai tone marks and upper and lower vowels are not counted.
  Runs of whitespace and line breaks count as one space, and text is NFC-normalised so decomposed accents count once.
- `netflix_timings_adjustment` scales the reading speed as a percentage, where higher values give shorter subtitles.
- Subtitles are extended to the greater of the reading time and `min_line_duration`.
  The user's minimum is respected rather than Netflix's 20 frames, though the default of 0.8 seconds is close.
- Extensions stop at 7 seconds, and 2 frames before the next subtitle.
  Gaps of 3 to 11 frames are closed to 2 frames, unless that would take a subtitle past 7 seconds.
  Gaps are rounded to whole frames at 24 fps, since timestamps are rarely frame-aligned.
- Extensions of 50 ms or less are ignored, because moving an end that may sit on a cut is not worth a frame or two of reading time.
- Lines are never shortened, and existing overlaps are left alone.

Not implemented:

- **Shot changes**, which would need the video.
  Translations are usually timed from subtitles that were hand-timed for another language, so their out-times may already sit on cuts.
- **Timing to audio**, such as starting on the first frame of speech and lingering half a second after it ends.
- **Vowel signs in Indic scripts**: the guides do not say whether they count as characters.
  LLM-Subtrans counts code points, so they do.
