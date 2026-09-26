#!/bin/bash

source ./envsubtrans/bin/activate
python scripts/sync_version.py
pip3 install --upgrade pip
pip install --upgrade pyinstaller
pip install --upgrade PyInstaller pyinstaller-hooks-contrib
pip install --upgrade setuptools
pip install --upgrade jaraco.text
pip install --upgrade charset_normalizer
./envsubtrans/bin/python -c "import torch" >/dev/null 2>&1 || {
    echo "Torch is required in the build environment before qwen-asr is installed."
    echo "Choose the hardware-appropriate command at https://pytorch.org/get-started/locally/"
    exit 1
}
pip install --upgrade -e ".[gui,openai,gemini,claude,mistral,qwen-asr]"

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

./envsubtrans/bin/pyinstaller --noconfirm \
    --additional-hooks-dir="hooks" \
    --exclude-module torch --exclude-module torchgen --exclude-module soynlp \
    --exclude-module gradio --exclude-module gradio_client --exclude-module av \
    --runtime-hook "hooks/rthook-nagisa-compat.py" \
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

./envsubtrans/bin/python -m pip install pip-audit
./envsubtrans/bin/python -m pip_audit
if [ $? -ne 0 ]; then
    echo "WARNING: Vulnerability scan detected known vulnerabilities. DO NOT publish or run this build!"
    exit 1
fi
