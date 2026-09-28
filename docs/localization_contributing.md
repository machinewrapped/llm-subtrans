# Localization Contributing Guide

Thanks for helping translate LLM-Subtrans! This guide explains the workflow, tools, and style rules for adding or improving translations.

## Overview

LLM-Subtrans uses GNU gettext. Translatable strings live in:
- Template (POT): `locales/gui-subtrans.pot`
- Per-language catalogs: `locales/<lang>/LC_MESSAGES/gui-subtrans.po`
- Compiled catalogs: `locales/<lang>/LC_MESSAGES/gui-subtrans.mo`

Strings are marked in code with:
- `_("text")` for simple strings
- `tr("context", "text")` for contextual strings (msgctxt)

A helper script automates extraction, merging, compilation, and a light-weight manual seeding flow.

## Quick start (recommended)

1) Install the project from source, if you only have a packaged version

2) Add your locale folder (example: Italian):
   - Create `locales/it/LC_MESSAGES/` (case sensitive)

3) Activate the virtual environment and run the one-stop workflow from the repo root:
   - `python scripts/update_translations.py`
   - This will:
     - Extract strings from application code to `locales/gui-subtrans.pot`
     - Ensure `locales/<lang>/LC_MESSAGES/gui-subtrans.po` exists
     - Compile `.po` → `.mo`
     - Generate `untranslated_msgids_<lang>.txt` listing empty translations

4) Either 
    - Translate automatically
      - Add `--auto` to send untranslated msgids to an LLM for translation
      - The OPENROUTER_API_KEY environment variable must be set to use this option
      - A free model will be used by default but it may be rate limited 
      - You can add the `--paid` argument to use a model that costs credits

    - Translate semi-automatically
        - Upload `untranslated_msgids_<lang>.txt` to your favourite LLM and ask it to fill in translations.
        - Make sure to mention that for keys like `max_completion_tokens` the translation should be human readable, e.g. "Max Completion Tokens" 

    - Translate using the generated dict file:
        - Open `untranslated_msgids_<lang>.txt`
        - Fill in each `''` with your translation (keep keys unchanged)

    - Or use translation tools
        - You can edit `locales/<lang>/LC_MESSAGES/gui-subtrans.po` with Poedit or any PO editor

5) Integrate and compile:
   - Run `python scripts/update_translations.py` again
   - Your translations are merged into the `.po` and `.mo` is recompiled

6) Test in app:
   - Launch the GUI and switch UI language in Settings. Some elements may not update until the app is restarted.

## What NOT to translate

- Provider identifiers, model names, protocol keywords, code snippets
- Placeholders and braces: keep `{name}` exactly (e.g. `{file}`, `{done}`, `{total}`)
- File globs and extensions: `*.srt`, `*.subtrans`, `All Files (*)`

## String rules and tips

- Preserve placeholders: if msgid has `{file}`, your translation must have `{file}` too.
- Translate settings keys, e.g. `ui_language` to a human-readable string, e.g. "UI Language"
- Quotes and braces:
  - Do not change `{}` names; do not add extra spaces inside them
  - Keep paired quotes symmetrical; escape in PO only if your editor requires it
- Punctuation and whitespace:
  - Preserve terminal punctuation (this seems to be a requirement in the PO tools)
  - Avoid trailing/leading spaces
- Context (msgctxt):
  - Some entries include context (e.g., `msgctxt "menu"`). Translate based on where/how it’s used.
  - If a context-specific translation is missing at runtime, the app falls back to the general (non-context) translation.
- UI length:
  - Try to keep text similar in length to the English to avoid layout issues
  - Prefer concise, action-focused wording for buttons and menus

## Style guidance

- Tone: clear, neutral, and consistent with platform UI norms for your language
- Capitalization: follow language-specific UI conventions (e.g., Spanish sentence case; English title case only where appropriate)
- Technical terms: favor commonly used localized equivalents

## Validate your translations

- Run: `python scripts/update_translations.py` (rebuilds POT/PO/MO and regenerates the untranslated_ids file - ideally this will be empty)
- Run tests: `python scripts/run_tests.py` (includes localization unit tests)
- Launch GUI and switch language in Settings; scan the UI for:
  - Truncated text
  - Misplaced placeholders
  - Encoding issues

## Common pitfalls

- Over-long labels: can clip in toolbars/menus; shorten if needed
- Breaking placeholders: `{file}` renamed or removed → runtime formatting errors
- Line breaks: multi-line strings must preserve intended formatting

## Adding a new language checklist

- [ ] Create `locales/<lang>/LC_MESSAGES/`
- [ ] Run `python scripts/update_translations.py`
- [ ] Fill `untranslated_msgids_<lang>.txt`
- [ ] Re-run the script to integrate and compile
- [ ] Test in-app and via `python scripts/run_tests.py`
- [ ] Commit updated `.po` (and optionally `.mo`) and any `untranslated_msgids_<lang>.txt` you used

## Submitting a PR

- Include your updated `locales/<lang>/LC_MESSAGES/gui-subtrans.po` and `.mo` files
- Note any tricky strings or context-sensitive decisions, or missing translations

## Tools
- Python 3.10+
- Optional: gettext (`msgmerge`, `msgfmt`) and/or Poedit
- Project scripts:
  - `scripts/update_translations.py` — end-to-end extraction, merge, compile, and dict seeding

## FAQ

- Q: My language’s names don’t show with friendly labels in the dropdown.
  - A: We use Babel when available to display language names; otherwise codes are shown. Functionality isn’t affected.

- Q: I translated a string but the app still shows English.
  - A: Ensure the `.po` has a non-empty `msgstr`, run the update script to compile, compare the msgid with the English text to make sure it is still current.

- Q: What if I add a new string to the code?
  - A: Add it in English wrapped with `_()` (or `tr()` if it needs context) and run `scripts/update_translations.py` to update the translation dictionary. It can then be translated using the above flow.
