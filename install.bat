@echo off
setlocal enabledelayedexpansion

set "PORTABLE_INSTALL="
set "CONFIG_PATH="
if /i "%~1"=="--portable" (
    set "PORTABLE_INSTALL=1"
) else if /i "%~1"=="--configpath" (
    if "%~2"=="" (
        echo Usage: install.bat [--portable ^| --configpath PATH]
        pause
        exit /b 1
    )
    if not "%~3"=="" (
        echo Usage: install.bat [--portable ^| --configpath PATH]
        pause
        exit /b 1
    )
    set "CONFIG_PATH=%~2"
) else if not "%~1"=="" (
    echo Usage: install.bat [--portable ^| --configpath PATH]
    pause
    exit /b 1
)

if defined PORTABLE_INSTALL (
    echo.
    echo ========================================
    echo Portable configuration mode enabled
    echo Settings and logs will be stored in .settings
    echo ========================================
) else if defined CONFIG_PATH (
    echo.
    echo ========================================
    echo Custom configuration mode enabled
    echo Settings and logs will be stored in "!CONFIG_PATH!"
    echo ========================================
)

REM Check if we're in the correct directory
if not exist "scripts" (
    echo Please run this script from the root directory of the project.
    pause
    exit /b 1
)

echo Checking if Python 3 is installed...
python --version >nul 2>&1
if errorlevel 1 (
    echo Python 3 not found. Please install Python 3 and try again.
    pause
    exit /b 1
)

REM Get Python version and check if it's 3.10 or higher
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo Python version: %PYTHON_VERSION%

REM Simple version check (assumes format like "3.11.0")
for /f "tokens=1,2 delims=." %%a in ("%PYTHON_VERSION%") do (
    set MAJOR=%%a
    set MINOR=%%b
)

if %MAJOR% lss 3 (
    echo Detected Python version is less than 3.10.0. Please upgrade your Python version.
    pause
    exit /b 1
)
if %MAJOR% equ 3 if %MINOR% lss 10 (
    echo Detected Python version is less than 3.10.0. Please upgrade your Python version.
    pause
    exit /b 1
)

echo Python version is compatible.

echo Checking if "envsubtrans" folder exists...
if exist "envsubtrans" (
    echo "envsubtrans" folder already exists.
    set "user_choice="
    set /p user_choice="Do you want to perform a clean install? This will delete the existing environment. (Y/N): "
    if /i "!user_choice!"=="Y" (
        echo Performing a clean install...
        rmdir /s /q envsubtrans
        if exist .env del .env
    ) else if /i "!user_choice!" neq "N" (
        echo Invalid choice. Exiting installation.
        pause
        exit /b 1
    )
)

set "EXTRAS="
set "SCRIPTS=llm-subtrans batch-translate transcribe"

echo Select installation type:
echo 1 = Install with GUI
echo 2 = Install command line tools only
set "install_choice="
set /p install_choice="Enter your choice (1/2): "

if "%install_choice%"=="2" (
    echo Installing command line modules...
) else (
    echo Including GUI modules...
    if "!EXTRAS!"=="" (set "EXTRAS=gui") else (set "EXTRAS=!EXTRAS!,gui")
    set "SCRIPTS=!SCRIPTS! gui-subtrans"
)

echo.
if defined CONFIG_PATH (
    if not exist "!CONFIG_PATH!" mkdir "!CONFIG_PATH!"
) else if defined PORTABLE_INSTALL (
    if not exist .settings mkdir .settings
)

if defined PORTABLE_INSTALL if exist .env (
    (findstr /v /b /c:"LLM_SUBTRANS_CONFIG_PATH=" .env) > .env.tmp
    move .env.tmp .env >nul 2>&1
)

if defined CONFIG_PATH call :set_env_var LLM_SUBTRANS_CONFIG_PATH CONFIG_PATH

REM Optional: configure OpenRouter API key
echo.
echo Optional: Configure OpenRouter API key (default provider)
set "openrouter_key="
set /p openrouter_key="Enter your OpenRouter API Key (optional): "
if defined openrouter_key call :set_env_var OPENROUTER_API_KEY openrouter_key

echo.
echo Select additional providers to install:
echo 0 = None
echo 1 = OpenAI
echo 2 = Google Gemini
echo 3 = Anthropic Claude
echo 4 = DeepSeek
echo 5 = Mistral
echo 6 = Bedrock (AWS)
echo a = All except Bedrock
set "provider_choice="
set /p provider_choice="Enter your choice (0/1/2/3/4/5/6/a): "

if "!provider_choice!"=="0" (
    echo No additional provider selected.
) else if "!provider_choice!"=="1" (
    call :install_provider "OpenAI" "OPENAI" "openai" "gpt-subtrans" "set_default"
) else if "!provider_choice!"=="2" (
    call :install_provider "Google Gemini" "GEMINI" "gemini" "gemini-subtrans" "set_default"
) else if "!provider_choice!"=="3" (
    call :install_provider "Claude" "CLAUDE" "claude" "claude-subtrans" "set_default"
) else if "!provider_choice!"=="4" (
    call :install_provider "DeepSeek" "DEEPSEEK" "" "deepseek-subtrans" "set_default"
) else if "!provider_choice!"=="5" (
    call :install_provider "Mistral" "MISTRAL" "mistral" "mistral-subtrans" "set_default"
) else if "!provider_choice!"=="6" (
    call :install_bedrock
) else if /i "!provider_choice!"=="a" (
    call :install_provider "Google Gemini" "GEMINI" "gemini" "gemini-subtrans" ""
    call :install_provider "OpenAI" "OPENAI" "openai" "gpt-subtrans" ""
    call :install_provider "Claude" "CLAUDE" "claude" "claude-subtrans" ""
    call :install_provider "Mistral" "MISTRAL" "mistral" "mistral-subtrans" ""
    call :install_provider "DeepSeek" "DEEPSEEK" "" "deepseek-subtrans" ""
) else (
    echo Invalid choice. Exiting installation.
    pause
    exit /b 1
)

echo.
:prompt_local_transcription
set "install_transcription="
set /p install_transcription="Install local transcription? (y/n): "

if /i "!install_transcription!"=="y" (
    call :install_qwen_local
) else if /i "!install_transcription!"=="n" (
    echo No local transcription selected. Cloud transcription remains available.
) else (
    echo Please enter y or n.
    goto prompt_local_transcription
)

REM Create or update the virtual environment
if not exist "envsubtrans" (
    echo.
    echo Creating virtual environment...
    python -m venv --upgrade-deps envsubtrans
    if errorlevel 1 (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
)

call envsubtrans\Scripts\activate.bat

REM Determine install target
set "INSTALL_TARGET=."
if not "!EXTRAS!"=="" (
    echo Installing dependencies: !EXTRAS!
    set "INSTALL_TARGET=.[!EXTRAS!]"
) else (
    echo Installing dependencies...
)

REM Install dependencies
.\envsubtrans\Scripts\python.exe -m pip install --upgrade -e "!INSTALL_TARGET!"
if errorlevel 1 (
    echo Failed to install required modules.
    pause
    exit /b 1
)

REM Qt no longer ships bundled fonts; create the expected directory so Qt's font
REM discovery does not emit a warning when running headless (offscreen) tests.
for /f "delims=" %%P in ('.\envsubtrans\Scripts\python.exe -c "import PySide6, os; print(os.path.join(os.path.dirname(PySide6.__file__), 'lib', 'fonts'))"') do set "QT_FONTS_DIR=%%P"
if not exist "!QT_FONTS_DIR!" mkdir "!QT_FONTS_DIR!" >nul 2>&1

if /i "!install_transcription!"=="y" (
    echo.
    echo Detecting GPU hardware and installing torch...
    .\envsubtrans\Scripts\python.exe scripts\install_torch.py
    set TORCH_EXIT=!errorlevel!

    if !TORCH_EXIT! equ 2 (
        echo.
        echo Warning: torch installation encountered an error.
        echo Skipping local transcription; cloud transcription remains available.
    ) else (
        echo.
        echo Installing local transcription package...
        .\envsubtrans\Scripts\python.exe scripts\install_qwen_runtime.py
        if errorlevel 1 (
            echo Failed to install the Qwen runtime.
        ) else if !TORCH_EXIT! equ 1 (
            echo.
            echo No GPU-accelerated torch variant was detected.
            echo CPU inference is disabled by default. Enable allow_cpu_fallback in Qwen Local advanced settings to consent to slow CPU inference.
            echo For GPU acceleration, install the hardware-appropriate PyTorch build from:
            echo   https://pytorch.org/get-started/locally/
        ) else (
            echo.
            echo Local transcription installed successfully with GPU support.
        )
    )
    echo.
)

REM Generate command scripts
for %%s in (!SCRIPTS!) do (
    call scripts\generate-cmd.bat %%s
)

goto setup_complete

:install_provider
set provider_name=%~1
set api_key_var_name=%~2
set extra_name=%~3
set script_name=%~4
set set_as_default=%~5

REM set /p keeps the old value on empty input, so clear it or the previous provider's key is reused
set "api_key="
set /p api_key="Enter your %provider_name% API Key (optional): "

REM Only update .env if user entered a new API key
if defined api_key call :set_env_var %api_key_var_name%_API_KEY api_key

REM Set as default provider if requested
if "%set_as_default%"=="set_default" call :set_env_var PROVIDER provider_name
if not "%extra_name%"=="" (
    if "!EXTRAS!"=="" (set "EXTRAS=%extra_name%") else (set "EXTRAS=!EXTRAS!,%extra_name%")
)
set "SCRIPTS=!SCRIPTS! %script_name%"
goto :eof

:install_bedrock
echo WARNING: Amazon Bedrock setup is not recommended for most users.
echo The setup requires AWS credentials, region configuration, and enabling specific model access in the AWS Console.
echo Proceed only if you are familiar with AWS configuration.
echo.

set "access_key="
set "secret_key="
set "region="
set /p access_key="Enter your AWS Access Key ID: "
set /p secret_key="Enter your AWS Secret Access Key: "
set /p region="Enter your AWS Region (e.g., us-east-1): "

set "provider_name=Bedrock"
call :set_env_var PROVIDER provider_name
call :set_env_var AWS_ACCESS_KEY_ID access_key
call :set_env_var AWS_SECRET_ACCESS_KEY secret_key
call :set_env_var AWS_REGION region

if "!EXTRAS!"=="" (set "EXTRAS=bedrock") else (set "EXTRAS=!EXTRAS!,bedrock")
set "SCRIPTS=!SCRIPTS! bedrock-subtrans"

echo Bedrock setup complete. Default provider set to Bedrock.
goto :eof

:install_qwen_local
REM qwen-asr is installed separately after GPU torch detection -- do not add to EXTRAS
goto :eof

:set_env_var
REM Write NAME=value to .env, replacing any existing NAME entry.
REM Usage: call :set_env_var NAME value_variable_name
REM The value is passed by variable name and expanded with !...! so special characters are written literally.
if exist .env (
    REM Anchored at line start so other keys ending in NAME= are kept
    (findstr /v /b /c:"%~1=" .env) > .env.tmp
    move .env.tmp .env >nul 2>&1

    REM Terminate an unterminated last line so the new entry is not merged into it.
    REM The marker only starts a line if .env already ends with a newline.
    (type .env & echo __LLM_SUBTRANS_EOF__) | findstr /b /c:"__LLM_SUBTRANS_EOF__" >nul
    if errorlevel 1 echo.>> .env
)
echo %~1=!%~2!>> .env
goto :eof

:setup_complete
echo.
echo Setup completed successfully. To uninstall just delete the directory.
pause
exit /b 0
