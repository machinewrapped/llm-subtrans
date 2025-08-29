# Copilot Instructions for LLM-Subtrans

These instructions help AI coding agents work effectively in this repository. Follow the patterns and workflows used by this project.

## Architecture overview
- Desktop GUI app using PySide6 (Qt for Python) with MVC-ish separation:
  - GUI/ contains views, dialogs, toolbars, and controllers that emit/handle Qt signals.
  - GUI/Commands/ contains background tasks implemented as QRunnable-based `Command` objects. They run via `GUI/CommandQueue.py` (QThreadPool) and update the UI by queueing `ModelUpdate`s.
  - GUI/ViewModel/ contains Qt model items (`SceneItem`, `BatchItem`, `LineItem`) and `ProjectViewModel` that maps subtitle data into a hierarchical model for views.
  - PySubtitle/ contains domain logic: parsing subtitle/project files, batching scenes, validation, translation provider abstraction, etc.
  - scripts/gui-subtrans.py is the GUI entrypoint. Initialize localization before creating the main window.
- Data flow:
  - User actions -> `GUI/ProjectActions.py` -> queue `GUI/Commands/*` via `GUI/GuiInterface.py` -> commands modify domain objects -> produce `GUI/ViewModel/ViewModelUpdate` patches -> `ProjectDataModel.UpdateViewModel` applies patches -> Qt model/view updates.
  - Long-running operations (translate, split/merge) are Commands. Commands must be thread-safe and use model updates; never mutate Qt widgets from worker threads.

Consult `docs/architecture.md` for detailed information on the project structure and architecture.

## Code Style
- **Language version**: The project uses and requires Python 3.10+
- **Naming**: PascalCase for classes and methods, snake_case for variables
- **Imports**: Standard lib → third-party → local, alphabetical within groups
- **Types**: Use type hints for parameters, return values, and class variables
- **Docstrings**: Triple-quoted concise descriptions for classes and methods
- **Error handling**: Custom exceptions, specific except blocks, input validation
- **Class structure**: Docstring → constants → init → properties → public methods → private methods
- **Threading safety**: Use locks (RLock/QRecursiveMutex) for thread-safe operations

## Localization (i18n)
- Use `from PySubtitle.Helpers.Localization import _` and wrap user-visible strings with `_()`.
- Templates live in `locales/gui-subtrans.pot`; languages under `locales/<lang>/LC_MESSAGES/gui-subtrans.po`.
- Dev workflows:
  - Extract: `python locales/extract_strings.py`
  - Merge & compile: `python locales/update_translations.py`
  - Spanish seeding helper: `python locales/seed_es_translations.py` (fills empty msgstr only).
- Initialize i18n early in `scripts/gui-subtrans.py`: `initialize_localization(options.get('ui_language'))`.

## Commands and threading
- Implement commands in `GUI/Commands/` by subclassing `GUI.Command.Command` (QRunnable + QObject):
  - Set flags: `is_blocking`, `skip_undo`, `can_undo` appropriately.
  - Place long work in `execute()`; emit updates via `self.AddModelUpdate()` and do not touch widgets directly.
  - Use `ProjectDataModel` to access domain (`SubtitleProject`, provider, options). Use validators where applicable.
- Queue via `GuiInterface.QueueCommand` or `ProjectActions.QueueCommand`. For immediate operations use `ExecuteCommandNow`.
- Respect undo/redo patterns: if not undoable, set `skip_undo=True` or `can_undo=False`.

## Project-specific conventions
- Logging uses Python `logging`; prefer informative messages. Debug noise is okay but wrap user-visible messages with `_()`.
- Options are centralized in `PySubtitle/Options.py` and accessed via `Options` instances; avoid scattering config.
- Model updates: see `GUI/ViewModel/ViewModelUpdate.py` and usage across commands for the update DSL (`add`, `update`, `remove`, `replace`).
- Providers: abstracted via `PySubtitle/TranslationProvider`. Use `TranslationProvider.get_providers()` to list and `get_provider(options)` to construct.

## Common tasks
- Run GUI: `python scripts/gui-subtrans.py [--firstrun] [file.srt]`
- Build distro: `scripts/makedistro.bat` (Windows) or `scripts/makedistro.sh` (Unix)
- Install deps: `install.bat` (Windows) or `./install.sh`
- Tests (if present): `python scripts/run_tests.py` or `python -m unittest ...`

## Patterns to follow
- GUI strings: use `_()`; for contextual disambiguation, use `tr(context, text)`.
- File dialogs and status messages are localized; follow existing patterns in `GUI/ProjectActions.py` and `GUI/MainWindow.py`.
- Use `GetResourcePath(...)` for assets/themes so paths work in packaged builds.
- Keep GUI updates on main thread; background work in Commands with `QThreadPool`.

## Examples
- Localized action creation (see `GUI/MainToolbar.py`):
  ```python
  action = QAction(_(name)); action.setToolTip(_(tooltip))
  ```
- Command model update (see `GUI/Commands/EditLineCommand.py`):
  ```python
  update = self.AddModelUpdate()
  update.lines.update((scene, batch, line), { 'translation': text })
  ```

## Gotchas
- Do not directly modify Qt widgets from worker threads; only via model updates/signals.
- When adding new user-facing strings, re-run extract/merge to keep POT/PO up to date.
- Keep provider-specific identifiers (API model names) un-translated in UI text.
- Secrets are stored in a .env file - you must never read the contents of the file.

If anything is unclear, open an issue or check `CLAUDE.md` for dev conventions.
