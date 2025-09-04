# LLM-Subtrans Development Guide

Project uses Python 3.10+. NEVER import or use deprecated typing members like List, Union or Iterator.

GUI framework is PySide6, be sure to use the correct syntax (e.g. scoped enum values).

Secrets are stored in a .env file - NEVER read the contents of the file.

Always run the unit_tests at the end of a task to validate the change.

## Console Output
Avoid Unicode characters (✓ ✗) in print/log messages as these trigger Windows console errors

## Commands
- Run all unit tests: `python tests/unit_tests.py` 
- Run single test: `python -m unittest PySubtitle.UnitTests.test_MODULE` or `python -m unittest GUI.UnitTests.test_MODULE`
- Build distribution: `./scripts/makedistro.sh` (Linux/Mac) or `scripts\makedistro.bat` (Windows)
- Create virtual environment, install dependencies and configure project: `./install.sh` (Linux/Mac) or `install.bat` (Windows)

## Code Style
- **Naming**: PascalCase for classes and methods, snake_case for variables
- **Imports**: Standard lib → third-party → local, alphabetical within groups
- **Class structure**: Docstring → constants → init → properties → public methods → private methods
- **Type Hints**: Use type hints for parameters, return values, and class variables
  - NEVER put spaces around the `|` in type unions. Use `str|None`, never `str | None`
  - ALWAYS put spaces around the colon introducing a type hint:
  - Examples: `def func(self, param : str) -> str|None:` ✅ `def func(self, param: str) -> str | None:` ❌
- **Docstrings**: Triple-quoted concise descriptions for classes and methods
- **Error handling**: Custom exceptions, specific except blocks, input validation, logging.warning/error
  - User-facing error messages should be localizable, using _()
- **Threading safety**: Use locks (RLock/QRecursiveMutex) for thread-safe operations
- **Unit Tests**: New tests must be registered in `PySubtitle.UnitTests.__init__` or `GUI.UnitTests.__init__`
  - Tests should adhere to the project test structure - see `GUI\UnitTests\test_BatchCommands.py` for an example.
  - Use functions like `log_input_expected_result` (logs input value, expected result and actual result or suitable proxies) defined in `Helpers\Test.py`.
  - **CRITICAL**: Always call `log_input_expected_result()` BEFORE the corresponding assertion so that if the assertion fails the log will show the reason.
  - **Pattern**: `log_input_expected_result("desc", expected, actual)` then `self.assertEqual(expected, actual)`
  - **None Safety**: Use `.get(key, default)` with appropriate default values to avoid Pylance warnings, or assert then test for None values.
  - **Regular Expressions**: The project uses the `regex` module for regular expression handling, rather than the standard `re`.

## Information
Consult `docs/architecture.md` for detailed information on the project architecture and components.
