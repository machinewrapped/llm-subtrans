#!/bin/bash

source ./envsubtrans/bin/activate
python scripts/sync_version.py
pip3 install --upgrade pip
pip install --upgrade pyinstaller
pip install --upgrade PyInstaller pyinstaller-hooks-contrib
pip install --upgrade setuptools
pip install --upgrade jaraco.text
pip install --upgrade charset_normalizer
pip install --upgrade -e ".[gui,openai,gemini,claude,mistral]"

# Remove boto3 from packaged version
pip uninstall boto3

./envsubtrans/bin/python scripts/update_translations.py

./envsubtrans/bin/python tests/unit_tests.py
if [ $? -ne 0 ]; then
    echo "Unit tests failed. Exiting..."
    exit $?
fi

./envsubtrans/bin/pyinstaller --noconfirm \
    --additional-hooks-dir="hooks" \
    --paths="./envsubtrans/lib" \
    --add-data "theme/*:theme/" \
    --add-data "assets/*:assets/" \
    --add-data "instructions/*:instructions/" \
    --add-data "LICENSE:." \
    --add-data "locales/*:locales/" \
    --noconfirm \
    scripts/gui-subtrans.py
