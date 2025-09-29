# LLM-Subtrans Development Guide

Project uses Python 3.10+. NEVER import or use deprecated typing members like List, Union or Iterator.

GUI framework is PySide6, be sure to use the correct syntax (e.g. scoped enum values).

Secrets are stored in a .env file - NEVER read the contents of the file.

Run tests\unit_tests.py at the end of a task to validate the change, unless it purely touched UI code (the GUI is not covered by unit tests).

## Console Output
Avoid Unicode characters (✓ ✗) in print/log messages as these trigger Windows console errors

## Commands
- Run all unit tests: `python tests/unit_tests.py` 
- Run single test: `python -m unittest PySubtrans.UnitTests.test_MODULE` or `python -m unittest GuiSubtrans.UnitTests.test_MODULE`
- Run full test suite: `python scripts/run_tests.py` 
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
- **Unit Tests**: Follow project test structure and use proper logging for debugging.
  - **Key Principles**:
    - Use semantic assertions (`assertIsNotNone`, `assertIn`, `assertEqual`) over generic `assertTrue` 
    - Call `log_input_expected_result(input, expected, actual)` BEFORE the assertion to log useful diagnostic data
    - Log informative input values (actual input value for the test case, field names being compared)
  - **Common Patterns**:
    - **Equality**: `log_input_expected_result("field_name", expected, obj.field); self.assertEqual(obj.field, expected)`
    - **Type checks**: `log_input_expected_result(obj, ExpectedClass, type(obj)); self.assertEqual(type(obj), ExpectedClass)`
    - **None checks**: `log_input_expected_result(obj, True, obj is not None); self.assertIsNotNone(obj)`
    - **Membership**: `log_input_expected_result("key_name", True, "key" in data); self.assertIn("key", data)`
  - **Exception Tests**: Guard with `skip_if_debugger_attached("TestName")` for debugging compatibility
    - Use `log_input_expected_error(input, ExpectedException, actual_exception)` for exception logging
  - **None Safety**: Use `.get(key, default)` with appropriate default values to avoid Pylance warnings, or assert then test for None values.
  - **Regular Expressions**: The project uses the `regex` module for regular expression handling, rather than the standard `re`.

## Information
Consult `docs/architecture.md` for detailed information on the project architecture and components.
