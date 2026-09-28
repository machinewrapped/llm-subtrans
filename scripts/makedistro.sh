#!/bin/bash

source envsubtrans/bin/activate
python scripts/sync_version.py
# Torch and the Qwen runtime are installed into an external environment by the application, not bundled
pip install --upgrade -e ".[gui,openai,gemini,claude,mistral,bedrock]"

python scripts/update_translations.py

python tests/unit_tests.py || exit 1
python tests/integration_tests.py || exit 1

# numpy and the packages built on it are optional imports of openai (pandas) and httpx's command-line client (pygments, PIL).
# The Qwen runtime brings its own copies, which a bundled numpy would shadow.
# cython is an optional import of pydantic.v1, present when the Qwen runtime is installed in the build environment.
pyinstaller --noconfirm --additional-hooks-dir="hooks" \
    --exclude-module torch --exclude-module torchgen \
    --exclude-module numpy --exclude-module scipy --exclude-module numba --exclude-module llvmlite \
    --exclude-module pandas --exclude-module PIL --exclude-module cython \
    --add-data "theme/*:theme/"  --add-data "assets/*:assets/" \
    --add-data "instructions/*:instructions/" \
    --add-data "LICENSE:." \
    --add-data "assets/gui-subtrans.ico:." \
    --add-data "locales/*:locales/" \
    scripts/gui-subtrans.py || exit $?

./envsubtrans/bin/python scripts/prepare_external_torch.py \
    --metadata-only \
    --metadata-path "dist/gui-subtrans/_internal/assets/frozen-python-compatibility.json" || exit 1

./envsubtrans/bin/python scripts/collect_third_party_notices.py --dist-dir "dist/gui-subtrans" || exit 1

pip install pip-audit
python -m pip_audit --cache-dir build/pip-audit-cache
if [ $? -ne 0 ]; then
    echo "WARNING: Vulnerability scan detected known vulnerabilities. DO NOT publish or run this build!"
    exit 1
fi

python scripts/check_package_ages.py
if [ $? -ne 0 ]; then
    exit 1
fi
