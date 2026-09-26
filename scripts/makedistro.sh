#!/bin/bash

source envsubtrans/bin/activate
python scripts/sync_version.py
python -c "import torch" >/dev/null 2>&1 || {
    echo "Torch is required in the build environment before qwen-asr is installed."
    echo "Choose the hardware-appropriate command at https://pytorch.org/get-started/locally/"
    exit 1
}
pip install --upgrade -e ".[gui,openai,gemini,claude,mistral,bedrock,qwen-asr]"

python scripts/update_translations.py

python tests/unit_tests.py || exit 1
python tests/integration_tests.py || exit 1

pyinstaller --noconfirm --additional-hooks-dir="hooks" \
    --exclude-module torch --exclude-module torchgen --exclude-module soynlp \
    --exclude-module gradio --exclude-module gradio_client --exclude-module av \
    --runtime-hook "hooks/rthook-nagisa-compat.py" \
    --add-data "theme/*:theme/"  --add-data "assets/*:assets/" \
    --add-data "instructions/*:instructions/" \
    --add-data "LICENSE:." \
    --add-data "assets/gui-subtrans.ico:." \
    --add-data "locales/*:locales/" \
    scripts/gui-subtrans.py || exit $?

./envsubtrans/bin/python scripts/prepare_external_torch.py \
    --metadata-only \
    --metadata-path "dist/gui-subtrans/_internal/assets/frozen-python-compatibility.json" || exit 1

pip install pip-audit
python -m pip_audit
if [ $? -ne 0 ]; then
    echo "WARNING: Vulnerability scan detected known vulnerabilities. DO NOT publish or run this build!"
    exit 1
fi

python scripts/check_package_ages.py
if [ $? -ne 0 ]; then
    exit 1
fi
