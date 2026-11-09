call envsubtrans/scripts/activate
.\envsubtrans\Scripts\python.exe scripts/sync_version.py
.\envsubtrans\Scripts\python.exe -m pip install --upgrade pip

rem Skip releases less than 7 days old, so a malicious release is likely to be pulled before it is bundled.
set "UPLOAD_COOLDOWN=--uploaded-prior-to=P7D"
.\envsubtrans\Scripts\python.exe -m pip install %UPLOAD_COOLDOWN% pywin32-ctypes
.\envsubtrans\Scripts\python.exe -m pip install --upgrade %UPLOAD_COOLDOWN% pyinstaller
rem Torch and the Qwen runtime are installed into an external environment by the application, not bundled
.\envsubtrans\Scripts\python.exe -m pip install --upgrade %UPLOAD_COOLDOWN% -e ".[gui,openai,gemini,claude,mistral]"
rem pip install --upgrade "boto3"  REM Bedrock dependencies excluded

rem Update and compile localization files before tests/build
.\envsubtrans\scripts\python.exe scripts/update_translations.py

.\envsubtrans\scripts\python.exe tests/unit_tests.py
if %errorlevel% neq 0 (
    echo Unit tests failed. Exiting...
    exit /b %errorlevel%
)

.\envsubtrans\scripts\python.exe tests/integration_tests.py
if %errorlevel% neq 0 (
    echo Integration tests failed. Exiting...
    exit /b %errorlevel%
)

.\envsubtrans\scripts\pyinstaller --noconfirm ^
    --icon "assets/gui-subtrans.ico" ^
    --additional-hooks-dir="hooks" ^
    --exclude-module torch ^
    --exclude-module torchgen ^
    --add-data "theme/*;theme/" ^
    --add-data "assets/*;assets/" ^
    --add-data "instructions/*;instructions/" ^
    --add-data "LICENSE;." ^
    --add-data "locales/*;locales/" ^
    "scripts/gui-subtrans.py"
if errorlevel 1 (
    echo PyInstaller failed. Exiting...
    exit /b %errorlevel%
)

.\envsubtrans\Scripts\python.exe scripts\collect_third_party_notices.py --dist-dir "dist\gui-subtrans"
if errorlevel 1 (
    echo Failed to write third-party notices.
    exit /b 1
)

.\envsubtrans\Scripts\python.exe -m pip install %UPLOAD_COOLDOWN% pip-audit
.\envsubtrans\Scripts\python.exe -m pip_audit --cache-dir build\pip-audit-cache
if %errorlevel% neq 0 (
    echo WARNING: Vulnerability scan detected known vulnerabilities. DO NOT publish or run this build!
    exit /b %errorlevel%
)

.\envsubtrans\Scripts\python.exe scripts/check_package_ages.py
if %errorlevel% neq 0 (
    exit /b %errorlevel%
)
