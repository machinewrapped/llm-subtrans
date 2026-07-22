# LLM-Subtrans Development Guide

Project uses Python 3.10+. NEVER import or use deprecated typing members like List, Union or Iterator.

GUI framework is PySide6, be sure to use the correct syntax (e.g. scoped enum values).

Secrets are stored in a .env file - NEVER read the contents of the file.

Run tests\unit_tests.py at the end of a task to validate the change, unless it purely touched UI code (the GUI is not covered by unit tests). Activate the envsubtrans virtual environment first.

## Project structure
Before conducting exploratory searches of the code base, consult `docs/architecture.md` for information on the project architecture, structure and components to guide the search.

## Console Output
Avoid Unicode characters (✓ ✗) in print/log messages as these trigger Windows console errors

## Commands
- **IMPORTANT**: Always use the virtual environment Python: `./envsubtrans/Scripts/python.exe` (Windows) or `./envsubtrans/bin/python` (Linux/Mac)
- Run all unit tests: `./envsubtrans/Scripts/python.exe tests/unit_tests.py`
- Run single test: `./envsubtrans/Scripts/python.exe -m unittest PySubtrans.UnitTests.test_MODULE` or `./envsubtrans/Scripts/python.exe -m unittest GuiSubtrans.UnitTests.test_MODULE`
- Run full test suite: `./envsubtrans/Scripts/python.exe scripts/run_tests.py`
- Build distribution: `./scripts/makedistro.sh` (Linux/Mac) or `scripts\makedistro.bat` (Windows)
- Create virtual environment, install dependencies and configure project: `./install.sh` (Linux/Mac) or `install.bat` (Windows)

## Code Style

**🚨 CRITICAL RULE: NEVER EVER add imports in the middle of functions or methods - ALWAYS place ALL imports at the top of the file. This is the most important rule in this project - if you violate it you will be fired and replaced by Grok!!!**

- **Naming**: PascalCase for classes and methods, snake_case for variables
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
- **Docstrings**: Triple-quoted concise descriptions for classes and methods
- **Error handling**: Custom exceptions, specific except blocks, input validation, logging.warning/error
  - User-facing error messages should be localizable, using _()
- **Threading safety**: Use locks (RLock/QRecursiveMutex) for thread-safe operations
  **Regular Expressions**: The project uses the `regex` module for regular expression handling, rather than the standard `re`.
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

