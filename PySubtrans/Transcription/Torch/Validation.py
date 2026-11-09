"""Locate packages and interpreters in external Torch environments."""

import sys
from pathlib import Path


def CandidateSitePackagesPaths(root : Path) -> list[Path]:
    """Return standard venv site-packages directories to probe for packages."""
    python_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    return [
        root,
        root / "site-packages",
        root / "Lib" / "site-packages",
        root / "lib" / python_version / "site-packages",
    ]


def FindTorchSitePackages(root : Path) -> Path|None:
    """Return the first candidate path containing a ``torch`` package, or None."""
    for candidate in CandidateSitePackagesPaths(root):
        if candidate.is_dir() and (candidate / "torch").is_dir():
            return candidate.resolve()

    # A venv may have been created by a different Python minor version than the
    # running interpreter, so its versioned POSIX layout is not in the candidate
    # list. Detect it so the runtime can still use the environment's interpreter.
    for candidate in sorted(root.glob("lib/python*/site-packages")):
        if (candidate / "torch").is_dir():
            return candidate.resolve()

    return None


def HasTorchPackage(root : Path) -> bool:
    """Whether any standard venv layout under *root* contains a torch package."""
    return FindTorchSitePackages(root) is not None


def FindVenvPython(root : Path) -> Path|None:
    """Find a Windows or POSIX venv interpreter under *root*."""
    candidates = (root / "Scripts" / "python.exe", root / "bin" / "python")
    return next((candidate for candidate in candidates if candidate.is_file()), None)
