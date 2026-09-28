"""Discovery of Python interpreters and existing Torch installations.

Pure logic with no Qt or Torch imports, shared by the setup wizard and any
other consumer that needs to locate an interpreter for a new Torch
environment.  The running interpreter is the compatibility reference for
source runs; packaged builds use their frozen metadata instead.
"""

import glob
import importlib.util
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import regex

from PySubtrans.Helpers.Resources import GetAppDir
from PySubtrans.Transcription.Torch.Validation import (
    BuildCurrentCompatibility,
    CompareCompatibility,
    FindCompatibilityMetadata,
    HasTorchPackage,
    ProbeVenvCompatibility,
    ReadCompatibilityMetadata,
)


DEFAULT_TORCH_DIR_NAME = 'torch-env'

# Matches torch's own Requires-Python floor; an older interpreter can create
# a venv without error but pip install torch will then fail inside it.
MIN_PYTHON_VERSION = (3, 10)
PROBE_TIMEOUT_SECONDS = 5


def FindExistingTorch() -> str|None:
    """Locate an existing Torch installation, or return None.

    Checks the default install location next to the application first, then
    falls back to scanning ``sys.path``.
    """
    default_path = os.path.join(GetAppDir(), DEFAULT_TORCH_DIR_NAME)
    if HasTorchPackage(Path(default_path)):
        return default_path

    spec = importlib.util.find_spec('torch')
    if spec and spec.origin:
        torch_path = Path(spec.origin).parent
        for parent in (torch_path.parent, torch_path.parent.parent):
            if parent.name == 'site-packages':
                return str(parent.parent)
        return str(torch_path.parent)

    return None


def PythonMeetsMinimum(python : str) -> bool:
    """Whether an interpreter is new enough to install torch."""
    try:
        result = subprocess.run(
            [python, '-c', 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")'],
            capture_output=True,
            text=True,
            check=True,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
        major, minor = (int(part) for part in result.stdout.strip().split('.'))
        return (major, minor) >= MIN_PYTHON_VERSION
    except (subprocess.SubprocessError, OSError, ValueError) as e:
        logging.debug("Failed to probe candidate Python at %s: %s", python, e)
        return False


def CandidatePythons() -> list[str]:
    """Interpreters to try, most specific first.

    A frozen GUI app's PATH (especially on macOS when launched other than from
    a shell) often only exposes the OS's own bundled Python, which is commonly
    too old for torch -- so versioned names and a few well-known install
    locations are checked as well as bare 'python3'.
    """
    names = ['python3.13', 'python3.12', 'python3.11', 'python3.10', 'python3', 'python']
    candidates = [found for name in names if (found := shutil.which(name))]

    if sys.platform == 'darwin':
        for pattern in (
            '/opt/homebrew/opt/python@3.*/bin/python3.*',
            '/usr/local/opt/python@3.*/bin/python3.*',
            '/Library/Frameworks/Python.framework/Versions/3.*/bin/python3.*',
        ):
            candidates.extend(sorted(glob.glob(pattern), reverse=True))
    elif sys.platform == 'win32':
        py_launcher = shutil.which('py')
        if py_launcher:
            candidates.insert(0, py_launcher)
            candidates.extend(_PyLauncherInterpreters(py_launcher))

    # Preserve first-seen order; the same real path can surface twice
    # (e.g. a versioned PATH hit and a glob match resolving to the same file).
    seen : set[str] = set()
    unique_candidates = []
    for candidate in candidates:
        resolved = str(Path(candidate).resolve())
        if resolved not in seen:
            seen.add(resolved)
            unique_candidates.append(candidate)
    return unique_candidates


def ExpectedCompatibility() -> dict[str, object]|None:
    """Return the interpreter facts a selected environment has to match.

    Packaged builds carry frozen metadata.  Source runs have none, so the
    running interpreter is the reference instead -- Torch is loaded into this
    process in both cases, so its wheels must match either way.
    """
    metadata_path = FindCompatibilityMetadata()
    if metadata_path is not None:
        metadata = ReadCompatibilityMetadata(metadata_path)
        compatibility = metadata.get("compatibility")
        return compatibility if isinstance(compatibility, dict) else None

    if getattr(sys, 'frozen', False):
        return None

    return BuildCurrentCompatibility()


def FindCompatiblePython() -> str|None:
    """Locate an interpreter to build the Torch environment with.

    Torch is loaded into the frozen application's process, so its wheels must
    match the build's Python ABI, OS, architecture and pointer width.  Prefer
    an exact match and only fall back to any interpreter new enough for torch,
    so a mismatched environment is a deliberate last resort.
    """
    # Prefer the running interpreter if it's not frozen; the project's own
    # minimum supported version already satisfies torch's floor.
    if not getattr(sys, 'frozen', False):
        return sys.executable

    candidates = CandidatePythons()
    try:
        compatibility = ExpectedCompatibility()
    except (ValueError, RuntimeError) as error:
        logging.warning("Could not read frozen Python compatibility metadata: %s", error)
        compatibility = None

    if compatibility is not None:
        for candidate in candidates:
            actual = ProbeVenvCompatibility(Path(candidate))
            if actual is not None and not CompareCompatibility(actual, compatibility):
                return candidate

        logging.warning("No installed Python matches the frozen build's interpreter.")

    for candidate in candidates:
        if PythonMeetsMinimum(candidate):
            return candidate

    return None


def _PyLauncherInterpreters(py_launcher : str) -> list[str]:
    """Enumerate the interpreters registered with the Windows ``py`` launcher.

    Versioned names such as ``python3.12`` are rarely on PATH on Windows, so the
    launcher's own list is the reliable way to find an interpreter that matches
    the frozen build's ABI.
    """
    try:
        result = subprocess.run(
            [py_launcher, '-0p'],
            capture_output=True,
            text=True,
            check=True,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except (subprocess.SubprocessError, OSError) as e:
        logging.debug("Failed to list interpreters from the py launcher: %s", e)
        return []

    interpreters = []
    for line in result.stdout.splitlines():
        # The launcher pads the version/arch column from the path with a run
        # of spaces, so splitting on that (rather than any whitespace) keeps
        # a single space inside the path itself intact -- e.g. paths under
        # 'C:\Program Files\...' for an all-users install.
        segments = [segment for segment in regex.split(r'\s{2,}', line.strip()) if segment]
        if segments and os.path.isfile(segments[-1]):
            interpreters.append(segments[-1])
    return interpreters
