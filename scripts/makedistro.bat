call envsubtrans/scripts/activate
python scripts/sync_version.py
python.exe -m pip install --upgrade pip
pip install pywin32-ctypes
pip install --upgrade pyinstaller
pip install --upgrade -e ".[gui,openai,gemini,claude,mistral]"
rem pip install --upgrade "boto3"  REM Bedrock dependencies excluded

rem Update and compile localization files before tests/build
.\envsubtrans\scripts\python.exe scripts/update_translations.py

.\envsubtrans\scripts\python.exe tests/unit_tests.py
if %errorlevel% neq 0 (
    echo Unit tests failed. Exiting...
    exit /b %errorlevel%
)

.\envsubtrans\scripts\pyinstaller --noconfirm --additional-hooks-dir="hooks-subtrans" --add-data "theme/*;theme/" --add-data "assets/*;assets/" --add-data "instructions/*;instructions/" --add-data "LICENSE;." --add-data "locales/*;locales/" "scripts/gui-subtrans.py"
