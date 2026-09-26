call envsubtrans/scripts/activate
.\envsubtrans\Scripts\python.exe scripts/sync_version.py
.\envsubtrans\Scripts\python.exe -m pip install --upgrade pip
.\envsubtrans\Scripts\python.exe -m pip install pywin32-ctypes
.\envsubtrans\Scripts\python.exe -m pip install --upgrade pyinstaller
rem Torch and the Qwen runtime are installed into an external environment by the application, not bundled
.\envsubtrans\Scripts\python.exe -m pip install --upgrade -e ".[gui,openai,gemini,claude,mistral]"
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

rem numpy and the packages built on it are optional imports of openai (pandas) and httpx's command-line client (pygments, PIL).
rem The Qwen runtime brings its own copies, which a bundled numpy would shadow.
rem cython is an optional import of pydantic.v1, present when the Qwen runtime is installed in the build environment.
.\envsubtrans\scripts\pyinstaller --noconfirm ^
    --additional-hooks-dir="hooks" ^
    --exclude-module torch ^
    --exclude-module torchgen ^
    --exclude-module numpy ^
    --exclude-module scipy ^
    --exclude-module numba ^
    --exclude-module llvmlite ^
    --exclude-module pandas ^
    --exclude-module PIL ^
    --exclude-module cython ^
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

.\envsubtrans\Scripts\python.exe scripts\prepare_external_torch.py ^
    --metadata-only ^
    --metadata-path "dist\gui-subtrans\_internal\assets\frozen-python-compatibility.json"
if errorlevel 1 (
    echo Failed to write frozen Python compatibility metadata.
    exit /b 1
)

.\envsubtrans\Scripts\python.exe scripts\collect_third_party_notices.py --dist-dir "dist\gui-subtrans"
if errorlevel 1 (
    echo Failed to write third-party notices.
    exit /b 1
)

.\envsubtrans\Scripts\python.exe -m pip install pip-audit
.\envsubtrans\Scripts\python.exe -m pip_audit --cache-dir build\pip-audit-cache
if %errorlevel% neq 0 (
    echo WARNING: Vulnerability scan detected known vulnerabilities. DO NOT publish or run this build!
    exit /b %errorlevel%
)

.\envsubtrans\Scripts\python.exe scripts/check_package_ages.py
if %errorlevel% neq 0 (
    exit /b %errorlevel%
)
