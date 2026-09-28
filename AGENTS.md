# LLM-Subtrans Development Guide

Project uses Python 3.10+. NEVER import or use deprecated typing members like List, Union or Iterator.

GUI framework is PySide6, be sure to use the correct syntax (e.g. scoped enum values).

Secrets are stored in a .env file - the agent must NEVER read the contents of the file.

If testable code covered by unit tests was changed, ensure that unit_tests has been run before wrapping up a task.

## Commits
- NEVER push commits without approval from the user
- NEVER use `--no-verify` to bypass the pre-commit hook. The hook runs pyright type checking and errors must be fixed before committing. If pyright is not installed, install it with `pip install pyright` before committing.

## Project structure
Before conducting exploratory searches of the code base, consult `docs/architecture.md` for information on the project architecture, structure and components to guide the search. Keep it at the level of components: what they are, where they live and how they connect. Update it when that picture changes; how a component works belongs in its docstrings and comments.

## Console Output
**IMPORTANT** Avoid Unicode characters (✓ ✗) in print/log messages as these trigger Windows console errors

## Commands
- **IMPORTANT**: Always use the virtual environment Python: `./envsubtrans/Scripts/python.exe` (Windows) or `./envsubtrans/bin/python` (Linux/Mac)
- Run all unit tests: `./envsubtrans/Scripts/python.exe tests/unit_tests.py`
- Run single test: `./envsubtrans/Scripts/python.exe -m unittest PySubtrans.UnitTests.test_MODULE` or `./envsubtrans/Scripts/python.exe -m unittest GuiSubtrans.UnitTests.test_MODULE`
- Run full test suite: `./envsubtrans/Scripts/python.exe scripts/run_tests.py`
- Build distribution: `./scripts/makedistro.sh` (Linux/Mac) or `scripts\makedistro.bat` (Windows)
- Create virtual environment, install dependencies and configure project: `./install.sh` (Linux/Mac) or `install.bat` (Windows)

## Worktrees
A git worktree has no virtual environment of its own. Link `envsubtrans` from the main worktree before running tests or committing, otherwise the commands above and the pre-commit hook fail:
- Windows: `cmd /c mklink /J envsubtrans "<main-worktree>\envsubtrans"` (a junction, no admin rights needed)
- Linux/Mac: `ln -s "<main-worktree>/envsubtrans" envsubtrans`

**IMPORTANT** The agent that created the link removes it once the work is committed and pushed; don't leave it for the user. Remove it before any cleanup or archiving of the worktree, using the full absolute path in quotes, since it may contain spaces. These commands remove the link only if it is one, and never touch its contents:
- Windows (PowerShell): `$link = Get-Item -LiteralPath '<worktree>\envsubtrans' -Force; if ($link.LinkType -eq 'Junction') { $link.Delete() }`
- Linux/Mac: `[ -L "<worktree>/envsubtrans" ] && rm "<worktree>/envsubtrans"`

Check the main worktree's `envsubtrans` is intact afterwards.

NEVER use `rmdir /s`, `Remove-Item`, `rm -r` or any other recursive delete on the link. PowerShell's `rmdir` is an alias for `Remove-Item`. A recursive delete follows the link and empties the main worktree's `envsubtrans`, destroying the shared environment.

## Code Style
**🚨 CRITICAL RULE: NEVER add imports in the middle of functions or methods - imports MUST be at the top of the file. Exceptions may be made for lazy-loading expensive SDKs but must first be justified, approved and documented.**

- **Naming**: PascalCase for classes and methods, snake_case for variables
  - NEVER use bare `_` as a throwaway variable (e.g. `filepath, _ = ...`) - `_()` is the localization function and the assignment shadows it, causing UnboundLocalError. Use `_selected_filter`, `_dummy`, etc. instead
- **Imports**: Standard lib → third-party → local, alphabetical within groups
- **Class structure**: Docstring → constants → init → properties → public methods → private methods
- **Type Hints**: Use type hints for parameters, return values, and class variables
  - NEVER put spaces around the `|` in type unions. Use `str|None`, never `str | None`
  - ALWAYS put spaces around the colon introducing a type hint:
  - Examples: 
    `def func(self, param : str) -> str|None:` ✅ 
    `def func(self, param: str) -> str | None:` ❌
- **`# type: ignore` is forbidden** unless suppressing a known third-party library gap (e.g. missing stubs). Never use it to paper over a type mismatch in project code — fix the types instead.
  - When assigning a `dict[str, str]` to a `SettingsType` field, wrap it: `SettingsType(my_dict)` — or add a typed property/method to `Options` or the relevant class.
  - `SettingsType` has typed getters (`get_str`, `get_bool`, `get_int`, `get_dict`, etc.) — always prefer these over raw `.get()` when a specific type is expected.
- **Whitespace**: Use blank lines to group logical steps within a function and to set off comments. A dense block with no breaks is harder for a human to scan than one with a few well-placed gaps.
- **Comments**: Add docstrings to explain the purpose of classes and methods, and targeted comments to explain the "why" behind the code.
- **Docstrings**: Triple-quoted concise descriptions for classes and methods
- **Prose**: Prefer short, to-the-point sentences in comments and docstrings. Keep each sentence on its own line.
- **Error handling**: Custom exceptions, specific except blocks, input validation, logging.warning/error
  - User-facing error messages should be localizable, using _()
- **Eceptions**: Never use exceptions for expected cases or standard control flow, only for genuine error states.
- **Threading safety**: Use locks (RLock/QRecursiveMutex) for thread-safe operations
- **Regular Expressions**: The project uses the `regex` module for regular expression handling, rather than the standard `re`.
- **Unit Tests**: Extend `LoggedTestCase` from `PySubtrans.Helpers.TestCases` and use `assertLogged*` methods for automatic logging and assertions.
  - **Key Principles**:
    - Prefer `assertLogged*` helper methods over manual logging + standard assertions
    - Use semantic assertions over generic `assertTrue` - the helpers provide `assertLoggedEqual`, `assertLoggedIsNotNone`, `assertLoggedIn`, etc.
    - Include descriptive text as the first parameter to explain what is being tested
    - Optionally provide `input_value` parameter for additional context
  - **Common Patterns**:
    - **Equality**: `self.assertLoggedEqual("field_name", expected, obj.field)`
    - **Type checks**: `self.assertLoggedIsInstance("object type", obj, ExpectedClass)`
    - **None checks**: `self.assertLoggedIsNotNone("result", obj)`
    - **Membership**: `self.assertLoggedIn("key existence", "key", data)`
    - **Comparisons**: `self.assertLoggedGreater("count", actual_count, 0)`
    - **Custom logging**: `self.log_expected_result(expected, actual, description="custom check", input_value=input_data)`
  - **Exception Tests**: Guard with `skip_if_debugger_attached` decorator for debugging compatibility
    - Use `log_input_expected_error(input, ExpectedException, actual_exception)` for exception logging
  - **None Safety**: Use `.get(key, default)` with appropriate default values to avoid Pylance warnings, or assert then test for None values.
  - **Optional Dependencies**: Test modules must not have top-level imports of optional packages. Guard them with `importlib.util.find_spec` and skip the class with `@unittest.skipUnless`, mirroring the pattern used in the corresponding provider.
  - **No string assertions**: Never assert on the text of error messages, GUI label text, or status text — these are brittle and break when wording changes. Assert on behaviour: status codes, error levels, counts, types, return values.
    - Asserting that a log record was emitted at a given level with `assertLogs(level=...)` is fine.
  - **Expected logs**: Wrap calls that are expected to log warnings or errors in `with self.assertLogs(level=...)`, so they do not leak into the test output. Passing tests should never look as if they are failing/broken.
