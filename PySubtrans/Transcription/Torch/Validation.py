"""Shared validation logic for external Torch installations.

Used by TorchRuntime (runtime loader), TorchSetupDialog (GUI wizard), and
prepare_external_torch.py (CLI/build-time tool).  Pure validation — no Torch
imports, no Qt imports, no sys.path manipulation.
"""

import json
import logging
import platform
import struct
import subprocess
import sys
import sysconfig
from pathlib import Path

from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Resources import GetResourcePath


METADATA_FILENAME = "frozen-python-compatibility.json"
OFFICIAL_PYTORCH_SELECTOR = "https://pytorch.org/get-started/locally/"

_METADATA_KIND = "llm-subtrans-frozen-python-compatibility"
_METADATA_SCHEMA_VERSION = 1

_COMPATIBILITY_FIELDS = (
    "python_implementation", "python_abi", "python_version",
    "os", "architecture",
)

# Union of aliases from TorchRuntime and prepare_external_torch
_ARCHITECTURE_ALIASES : dict[str, str] = {
    "amd64": "x8664",
    "x8664": "x8664",
    "x86_64": "x8664",
    "aarch64": "arm64",
    "i386": "x86",
    "i486": "x86",
    "i586": "x86",
    "i686": "x86",
}


PROBE_TIMEOUT_SECONDS = 15


def NormaliseArchitecture(value : object) -> str:
    """Normalize common architecture spellings for comparison."""
    normalized = str(value or "").casefold().replace("-", "").replace("_", "")
    return _ARCHITECTURE_ALIASES.get(normalized, normalized)


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
    # list. Detect it anyway so callers can report compatibility rather than
    # claiming Torch is absent.
    for candidate in sorted(root.glob("lib/python*/site-packages")):
        if (candidate / "torch").is_dir():
            return candidate.resolve()

    return None


def HasTorchPackage(root : Path) -> bool:
    """Whether any standard venv layout under *root* contains a torch package."""
    return FindTorchSitePackages(root) is not None


def GetPythonAbi() -> str:
    """Return the interpreter ABI tag used by compatible extension wheels."""
    cache_tag = sys.implementation.cache_tag
    if cache_tag:
        return cache_tag

    soabi = sysconfig.get_config_var("SOABI")
    if soabi:
        return str(soabi)

    return f"{sys.implementation.name}{sys.version_info.major}{sys.version_info.minor}"


def BuildCurrentCompatibility() -> dict[str, object]:
    """Build the 6-field compatibility dict from the running interpreter."""
    version = sys.version_info
    return {
        "python_implementation": sys.implementation.name,
        "python_abi": GetPythonAbi(),
        "python_version": f"{version.major}.{version.minor}",
        "os": platform.system() or sys.platform,
        "architecture": platform.machine() or "unknown",
        "pointer_bits": struct.calcsize("P") * 8,
    }


def FindCompatibilityMetadata() -> Path|None:
    """Locate the frozen application's compatibility metadata file.

    Uses ``GetResourcePath`` so the file is found via ``sys._MEIPASS`` in
    frozen builds and via ``./assets/`` in development.  Returns None when
    the file does not exist (normal for non-frozen runs).
    """
    metadata_path = Path(GetResourcePath("assets", METADATA_FILENAME))
    return metadata_path if metadata_path.is_file() else None


def ReadCompatibilityMetadata(
    metadata_path : str|Path,
    *,
    error_type : type[Exception] = ValueError,
) -> dict[str, object]:
    """Read and validate frozen-build compatibility metadata.

    Raises *error_type* (default ``ValueError``) on any problem so that
    each consumer can raise its own exception hierarchy.
    """
    resolved = Path(metadata_path).expanduser().resolve()

    try:
        loaded = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise error_type(
            _("Torch compatibility metadata could not be read from '{}': {}").format(resolved, error)
        ) from error

    if not isinstance(loaded, dict):
        raise error_type(
            _("Torch compatibility metadata has an invalid format: {}").format(resolved)
        )

    if loaded.get("kind") != _METADATA_KIND:
        raise error_type(
            _("Torch compatibility metadata has an unknown kind: {}").format(resolved)
        )

    if loaded.get("schema_version") != _METADATA_SCHEMA_VERSION:
        raise error_type(
            _("Torch compatibility metadata schema is unsupported: {}").format(resolved)
        )

    compatibility = loaded.get("compatibility")
    if not isinstance(compatibility, dict) or any(
        not isinstance(compatibility.get(key), str) or not compatibility[key]
        for key in _COMPATIBILITY_FIELDS
    ) or type(compatibility.get("pointer_bits")) is not int or compatibility["pointer_bits"] not in (32, 64):
        raise error_type(
            _("Torch compatibility metadata has missing or invalid compatibility fields: {}").format(resolved)
        )

    return loaded


def CompareCompatibility(actual : dict[str, object], expected : dict[str, object]) -> list[str]:
    """Return the human-readable differences between two compatibility dicts.

    An empty list means the two describe the same Python ABI, platform, and
    pointer width.  Callers that must reject can raise on a non-empty result;
    callers that only warn can surface the details to the user.
    """
    mismatches : list[str] = []

    for key in (*_COMPATIBILITY_FIELDS, "pointer_bits"):
        observed = actual.get(key)
        required = expected.get(key)

        if key == "architecture":
            matches = NormaliseArchitecture(observed) == NormaliseArchitecture(required)
        else:
            matches = observed == required

        if not matches:
            mismatches.append(f"{key}: external={observed!r}, frozen={required!r}")

    return mismatches


def CheckCompatibility(
    actual : dict[str, object],
    expected : dict[str, object],
    *,
    error_type : type[Exception] = RuntimeError,
) -> None:
    """Compare two compatibility dicts and raise *error_type* on mismatch."""
    mismatches = CompareCompatibility(actual, expected)

    if mismatches:
        raise error_type(
            _("The external Torch installation is incompatible with this application: {}. "
              "Install a complete Torch environment matching the application's Python ABI, "
              "OS, architecture, and pointer width, then restart.").format("; ".join(mismatches))
        )


def FindVenvPython(root : Path) -> Path|None:
    """Find a Windows or POSIX venv interpreter under *root*."""
    candidates = (root / "Scripts" / "python.exe", root / "bin" / "python")
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def ProbeVenvCompatibility(python_executable : Path) -> dict[str, object]|None:
    """Read ABI and platform facts from a venv's own interpreter.

    Returns the compatibility dict on success, or None when the
    interpreter cannot be probed (missing, broken, timeout).
    """
    probe = (
        "import json,platform,struct,sys,sysconfig;"
        "v=sys.version_info;"
        "abi=sys.implementation.cache_tag or sysconfig.get_config_var('SOABI') or "
        "f'{sys.implementation.name}{v.major}{v.minor}';"
        "print(json.dumps({'python_implementation': sys.implementation.name,"
        "'python_abi': abi,"
        "'python_version': f'{v.major}.{v.minor}',"
        "'os': platform.system() or sys.platform,"
        "'architecture': platform.machine() or 'unknown',"
        "'pointer_bits': struct.calcsize('P') * 8}))"
    )
    try:
        result = subprocess.run(
            [str(python_executable), "-I", "-S", "-c", probe],
            capture_output=True,
            text=True,
            check=True,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
        parsed = json.loads(result.stdout)
        if isinstance(parsed, dict):
            return parsed
    except (subprocess.SubprocessError, OSError, ValueError) as e:
        logging.debug("Failed to probe venv Python at %s: %s", python_executable, e)

    return None
