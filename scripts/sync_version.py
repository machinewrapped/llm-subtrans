#!/usr/bin/env python3
import re
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
from PySubtrans import version as ver

pyproject = project_root / "pyproject.toml"
version = ver.__version__.lstrip('v')
content = pyproject.read_text()
content = re.sub(r'^version = ".*"', f'version = "{version}"', content, flags=re.MULTILINE)
pyproject.write_text(content)
print(f"Synced pyproject.toml version to {version}")
