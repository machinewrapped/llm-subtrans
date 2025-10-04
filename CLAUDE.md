# LLM-Subtrans Development Guide

Project uses Python 3.10+. NEVER import or use deprecated typing members like List, Union or Iterator.

GUI framework is PySide6, be sure to use the correct syntax (e.g. scoped enum values).

Secrets are stored in a .env file - NEVER read the contents of the file.

Run tests\unit_tests.py at the end of a task to validate the change, unless it purely touched UI code (the GUI is not covered by unit tests). Activate the envsubtrans virtual environment first.

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
- **Docstrings**: Triple-quoted concise descriptions for classes and methods
- **Error handling**: Custom exceptions, specific except blocks, input validation, logging.warning/error
  - User-facing error messages should be localizable, using _()
- **Threading safety**: Use locks (RLock/QRecursiveMutex) for thread-safe operations
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
  - **Regular Expressions**: The project uses the `regex` module for regular expression handling, rather than the standard `re`.

## Information
Consult `docs/architecture.md` for detailed information on the project architecture and components.
