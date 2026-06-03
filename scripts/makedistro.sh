#!/bin/bash

source envsubtrans/bin/activate
python scripts/sync_version.py
pip install --upgrade -e ".[gui,openai,gemini,claude,mistral,bedrock]"

python scripts/update_translations.py

pyinstaller --noconfirm --additional-hooks-dir="hooks-subtrans" \
    --add-data "theme/*:theme/"  --add-data "assets/*:assets/" \
    --add-data "instructions/*:instructions/" \
    --add-data "LICENSE:." \
    --add-data "assets/gui-subtrans.ico:." \
    --add-data "locales/*:locales/" \
    scripts/gui-subtrans.py

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
