call envsubtrans/scripts/activate
.\envsubtrans\Scripts\python.exe scripts/sync_version.py
.\envsubtrans\Scripts\python.exe -m pip install --upgrade pip
.\envsubtrans\Scripts\python.exe -m pip install pywin32-ctypes
.\envsubtrans\Scripts\python.exe -m pip install --upgrade pyinstaller
.\envsubtrans\Scripts\python.exe -m pip install --upgrade -e ".[gui,openai,gemini,claude,mistral]"
rem pip install --upgrade "boto3"  REM Bedrock dependencies excluded

rem Update and compile localization files before tests/build
.\envsubtrans\scripts\python.exe scripts/update_translations.py

.\envsubtrans\scripts\python.exe tests/unit_tests.py
if %errorlevel% neq 0 (
    echo Unit tests failed. Exiting...
    exit /b %errorlevel%
)

.\envsubtrans\scripts\pyinstaller --noconfirm ^
    --additional-hooks-dir="hooks" ^
    --add-data "theme/*;theme/" ^
    --add-data "assets/*;assets/" ^
    --add-data "instructions/*;instructions/" ^
    --add-data "LICENSE;." ^
    --add-data "locales/*;locales/" ^
    "scripts/gui-subtrans.py"

.\envsubtrans\Scripts\python.exe -m pip install pip-audit
.\envsubtrans\Scripts\python.exe -m pip_audit
if %errorlevel% neq 0 (
    echo WARNING: Vulnerability scan detected known vulnerabilities. DO NOT publish or run this build!
    exit /b %errorlevel%
)

.\envsubtrans\Scripts\python.exe scripts/check_package_ages.py
if %errorlevel% neq 0 (
    exit /b %errorlevel%
)
