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
