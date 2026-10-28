#!/bin/bash

source ./envsubtrans/bin/activate
python scripts/sync_version.py
pip3 install --upgrade pip

# Skip releases less than 7 days old, so a malicious release is likely to be pulled before it is bundled.
upload_cooldown="--uploaded-prior-to=P7D"
pip install --upgrade "$upload_cooldown" pyinstaller
pip install --upgrade "$upload_cooldown" PyInstaller pyinstaller-hooks-contrib
pip install --upgrade "$upload_cooldown" setuptools
pip install --upgrade "$upload_cooldown" jaraco.text
pip install --upgrade "$upload_cooldown" charset_normalizer
# Torch and the Qwen runtime are installed into an external environment by the application, not bundled
pip install --upgrade "$upload_cooldown" -e ".[gui,openai,gemini,claude,mistral]"

# Remove boto3 from packaged version
pip uninstall boto3

./envsubtrans/bin/python scripts/update_translations.py

./envsubtrans/bin/python tests/unit_tests.py
if [ $? -ne 0 ]; then
    echo "Unit tests failed. Exiting..."
    exit 1
fi

./envsubtrans/bin/python tests/integration_tests.py
if [ $? -ne 0 ]; then
    echo "Integration tests failed. Exiting..."
    exit 1
fi

# numpy and the packages built on it are optional imports of openai (pandas) and httpx's command-line client (pygments, PIL).
# The Qwen runtime brings its own copies, which a bundled numpy would shadow.
# cython is an optional import of pydantic.v1, present when the Qwen runtime is installed in the build environment.
./envsubtrans/bin/pyinstaller --noconfirm \
    --additional-hooks-dir="hooks" \
    --exclude-module torch --exclude-module torchgen \
    --exclude-module numpy --exclude-module scipy --exclude-module numba --exclude-module llvmlite \
    --exclude-module pandas --exclude-module PIL --exclude-module cython \
    --paths="./envsubtrans/lib" \
    --add-data "theme/*:theme/" \
    --add-data "assets/*:assets/" \
    --add-data "instructions/*:instructions/" \
    --add-data "LICENSE:." \
    --add-data "locales/*:locales/" \
    --noconfirm \
    scripts/gui-subtrans.py || exit $?

./envsubtrans/bin/python scripts/prepare_external_torch.py \
    --metadata-only \
    --metadata-path "dist/gui-subtrans/_internal/assets/frozen-python-compatibility.json" || exit 1

./envsubtrans/bin/python scripts/collect_third_party_notices.py --dist-dir "dist/gui-subtrans" || exit 1

./envsubtrans/bin/python -m pip install "$upload_cooldown" pip-audit
./envsubtrans/bin/python -m pip_audit --cache-dir build/pip-audit-cache
if [ $? -ne 0 ]; then
    echo "WARNING: Vulnerability scan detected known vulnerabilities. DO NOT publish or run this build!"
    exit 1
fi

./envsubtrans/bin/python scripts/check_package_ages.py || exit 1
