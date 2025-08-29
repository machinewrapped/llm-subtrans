# LLM-Subtrans Development Guide

Uses Python 3.10+ and PySide6. 
Never import or use outdated typing members like List and Union.

Secrets are stored in a .env file - you must never read the contents of the file.

## Commands
- Run all tests: `python scripts/unit_tests.py` or `python scripts/run_tests.py` 
- Run single test: `python -m unittest PySubtitle.UnitTests.test_MODULE` or `python -m unittest GUI.UnitTests.test_MODULE`
- Build distribution: `./scripts/makedistro.sh` (Linux/Mac) or `scripts\makedistro.bat` (Windows)
- Install dependencies: `./install.sh` (Linux/Mac) or `install.bat` (Windows)

## Code Style
- **Naming**: PascalCase for classes and methods, snake_case for variables
- **Imports**: Standard lib → third-party → local, alphabetical within groups
- **Types**: Use type hints for parameters, return values, and class variables
- **Type Hints**: 
  - **CRITICAL**: Do NOT put spaces around the `|` in type unions. Use `str|None`, never `str | None`
  - DO put spaces around the colon introducing a type hint:
  - Examples: `def func(self, param : str) -> str|None:` ✅ `def func(self, param: str) -> str | None:` ❌
- **Docstrings**: Triple-quoted concise descriptions for classes and methods
- **Error handling**: Custom exceptions, specific except blocks, input validation
- **Class structure**: Docstring → constants → init → properties → public methods → private methods
- **Threading safety**: Use locks (RLock/QRecursiveMutex) for thread-safe operations
- **Validation**: Validate inputs with helpful error messages
- **Console Output**: Avoid Unicode characters (✓ ✗) in print/log messages - Windows console encoding issues
- **Unit Tests**: Tests should follow a specific structure using methods like log_input_expected_result defined in `Helpers\Test.py`. See `GUI\UnitTests\test_BatchCommands.py` for an example.

## Information
Consult `docs/architecture.md` for detailed information on the project structure and architecture.
