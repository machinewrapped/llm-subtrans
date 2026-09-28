# Git Hooks

This directory contains git hooks for the llm-subtrans project.

## Available Hooks

### pre-commit

Runs pyright type checking before each commit to prevent type errors from being committed.

- **Speed**: ~6 seconds (analyzes 187 files)
- **Behavior**: Blocks commit if type errors are found
- **Bypass**: Use `git commit --no-verify` to skip the check

## Installation

### Windows

```bash
hooks\install.bat
```

### Linux/Mac

```bash
./hooks/install.sh
```

## Hook Details

The pre-commit hook:
- Detects the operating system and uses the appropriate Python path
- Runs `pyright --outputjson` to analyze the codebase
- Parses the JSON output to count errors and warnings
- Blocks the commit if any type errors are found
- Allows the commit if only warnings are present (warnings are logged but don't fail)
- Provides helpful error messages with instructions on how to see details or skip the check

## Uninstalling

To remove the hooks, simply delete them from `.git/hooks/`:

```bash
# Windows
del .git\hooks\pre-commit

# Linux/Mac
rm .git/hooks/pre-commit
```

## Customization

To modify the hooks, edit the files in this `hooks/` directory and re-run the install script.
