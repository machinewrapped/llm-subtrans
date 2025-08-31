@echo off
setlocal enabledelayedexpansion

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

echo Creating virtual environment...
python -m venv envsubtrans
if errorlevel 1 (
    echo Failed to create virtual environment.
    pause
    exit /b 1
)

call envsubtrans\Scripts\activate.bat

echo Installing required modules...
pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo Failed to install required modules.
    pause
    exit /b 1
)

call scripts\generate-cmd.bat gui-subtrans
call scripts\generate-cmd.bat llm-subtrans

REM Optional: configure OpenRouter API key
echo.
echo Optional: Configure OpenRouter API key (default provider)
set /p openrouter_key="Enter your OpenRouter API Key (optional): "
if not "!openrouter_key!"=="" (
    if exist .env (
        REM Remove existing OpenRouter API key
        (findstr /v "OPENROUTER_API_KEY=" .env) > .env.tmp
        move .env.tmp .env >nul 2>&1
    )
    echo OPENROUTER_API_KEY=!openrouter_key!>> .env
)

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
set /p provider_choice="Enter your choice (0/1/2/3/4/5/6/a): "

if "!provider_choice!"=="0" (
    echo No additional provider selected.
    goto setup_complete
)

if "!provider_choice!"=="1" (
    call :install_provider "OpenAI" "OPENAI" "openai" "gpt-subtrans" "set_default"
    goto setup_complete
)

if "!provider_choice!"=="2" (
    call :install_provider "Google Gemini" "GEMINI" "google-genai google-api-core" "gemini-subtrans" "set_default"
    goto setup_complete
)

if "!provider_choice!"=="3" (
    call :install_provider "Claude" "CLAUDE" "anthropic" "claude-subtrans" "set_default"
    goto setup_complete
)

if "!provider_choice!"=="4" (
    call :install_provider "DeepSeek" "DEEPSEEK" "" "deepseek-subtrans" "set_default"
    goto setup_complete
)

if "!provider_choice!"=="5" (
    call :install_provider "Mistral" "MISTRAL" "mistralai" "mistral-subtrans" "set_default"
    goto setup_complete
)

if "!provider_choice!"=="6" (
    call :install_bedrock
    goto setup_complete
)

if /i "!provider_choice!"=="a" (
    call :install_provider "Google Gemini" "GEMINI" "google-genai google-api-core" "gemini-subtrans" ""
    call :install_provider "OpenAI" "OPENAI" "openai" "gpt-subtrans" ""
    call :install_provider "Claude" "CLAUDE" "anthropic" "claude-subtrans" ""
    call :install_provider "Mistral" "MISTRAL" "mistralai" "mistral-subtrans" ""
    call :install_provider "DeepSeek" "DEEPSEEK" "" "deepseek-subtrans" ""
    goto setup_complete
)

echo Invalid choice. Exiting installation.
pause
exit /b 1

:install_provider
set provider_name=%~1
set api_key_var_name=%~2
set pip_package=%~3
set script_name=%~4
set set_as_default=%~5

set /p api_key="Enter your %provider_name% API Key (optional): "

REM Only update .env if user entered a new API key
if not "%api_key%"=="" (
    if exist .env (
        (findstr /v "%api_key_var_name%_API_KEY=" .env) > .env.tmp
        move .env.tmp .env >nul 2>&1
    )
    echo %api_key_var_name%_API_KEY=%api_key%>> .env
)

REM Set as default provider if requested
if "%set_as_default%"=="set_default" (
    if exist .env (
        (findstr /v "PROVIDER=" .env) > .env.tmp
        move .env.tmp .env >nul 2>&1
    )
    echo PROVIDER=%provider_name%>> .env
)
if not "%pip_package%"=="" (
    echo Installing %provider_name% module...
    pip install %pip_package%
    if errorlevel 1 (
        echo Failed to install %provider_name% module.
        pause
        exit /b 1
    )
) else (
    echo %provider_name% has no additional dependencies to install.
)
call scripts\generate-cmd.bat %script_name%
goto :eof

:install_bedrock
echo WARNING: Amazon Bedrock setup is not recommended for most users.
echo The setup requires AWS credentials, region configuration, and enabling specific model access in the AWS Console.
echo Proceed only if you are familiar with AWS configuration.
echo.

set /p access_key="Enter your AWS Access Key ID: "
set /p secret_key="Enter your AWS Secret Access Key: "
set /p region="Enter your AWS Region (e.g., us-east-1): "

if exist .env (
    REM Remove existing provider settings
    (findstr /v "AWS_ACCESS_KEY_ID=" .env) > .env.tmp
    (findstr /v "AWS_SECRET_ACCESS_KEY=" .env.tmp) > .env.tmp2
    (findstr /v "AWS_REGION=" .env.tmp2) > .env.tmp3
    (findstr /v "PROVIDER=" .env.tmp3) > .env.tmp4
    move .env.tmp4 .env >nul 2>&1
    del .env.tmp .env.tmp2 .env.tmp3 >nul 2>&1
)

echo PROVIDER=Bedrock>> .env
echo AWS_ACCESS_KEY_ID=%access_key%>> .env
echo AWS_SECRET_ACCESS_KEY=%secret_key%>> .env
echo AWS_REGION=%region%>> .env

echo Installing AWS SDK for Python (boto3)...
pip install -U boto3
if errorlevel 1 (
    echo Failed to install boto3.
    pause
    exit /b 1
)
call scripts\generate-cmd.bat bedrock-subtrans

echo Bedrock setup complete. Default provider set to Bedrock.
goto :eof

:setup_complete
echo.
echo Setup completed successfully. To uninstall just delete the directory.
pause
exit /b 0
