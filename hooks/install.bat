@echo off
REM Install git hooks for llm-subtrans
REM Run from project root: hooks\install.bat

setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "HOOKS_DIR=%PROJECT_ROOT%\.git\hooks"

if not exist "%HOOKS_DIR%" (
    echo Error: .git\hooks directory not found
    echo Make sure you're running this from the project root
    exit /b 1
)

echo Installing git hooks...

REM Copy pre-commit hook
copy /Y "%SCRIPT_DIR%pre-commit" "%HOOKS_DIR%\pre-commit" >nul

echo Installed hooks:
echo   - pre-commit ^(runs pyright type checking^)
echo.
echo To skip the pre-commit hook, use: git commit --no-verify
