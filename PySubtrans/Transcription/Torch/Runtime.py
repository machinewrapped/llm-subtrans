"""Runtime support for loading an optional external Torch installation."""

import logging
import os
import platform
import sys
from importlib.machinery import PathFinder
from pathlib import Path

from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import ConfigActionOption
from PySubtrans.Transcription.Torch.Validation import (
    METADATA_FILENAME,
    BuildCurrentCompatibility,
    CheckCompatibility,
    FindCompatibilityMetadata,
    FindTorchSitePackages,
    ReadCompatibilityMetadata,
)

class TorchConfigOption(ConfigActionOption):
    """Sentinel for the torch installation directory setting."""
    label = _("Set up local transcription...")


class TorchRuntimeError(ImportError):
    """Raised when the configured external Torch runtime cannot be used."""


_configured_path: Path|None = None
_dll_directories: list[object] = []


def _select_installation_path(installation_directory : str) -> Path:
    """Validate and resolve the configured site-packages directory."""
    root = Path(installation_directory).expanduser()
    result = FindTorchSitePackages(root)
    if result is not None:
        return result

    raise TorchRuntimeError(_(
        "The configured Torch installation directory is invalid. Select the external "
        "site-packages directory containing the 'torch' package."
    ))


def _validate_process_compatibility(installation_path : Path) -> None:
    """Reject plainly incompatible installations before changing import state."""
    if platform.architecture()[0] not in ("32bit", "64bit"):
        raise TorchRuntimeError(_("Unable to determine the Python process architecture for the external Torch installation."))

    # PathFinder performs an absolute, path-scoped lookup without consulting the
    # ambient sys.path or importing Torch from the frozen application.
    torch_spec = PathFinder.find_spec("torch", [str(installation_path)])
    if torch_spec is None:
        raise TorchRuntimeError(_("The external Torch installation cannot be inspected by this Python interpreter."))


def _validate_frozen_compatibility() -> None:
    """Validate the frozen Python target before loading external Torch."""
    metadata_path = FindCompatibilityMetadata()

    if metadata_path is None:
        if bool(getattr(sys, "frozen", False)):
            raise TorchRuntimeError(_(
                "This frozen application is missing '{}'. Repair or reinstall the distribution "
                "before configuring an external Torch installation."
            ).format(METADATA_FILENAME))
        return

    metadata = ReadCompatibilityMetadata(metadata_path, error_type=TorchRuntimeError)

    # ReadCompatibilityMetadata validates that compatibility is a well-formed dict
    compatibility = metadata["compatibility"]
    if not isinstance(compatibility, dict):
        return

    actual = BuildCurrentCompatibility()
    CheckCompatibility(actual, compatibility, error_type=TorchRuntimeError)


def _register_native_libraries(installation_path : Path) -> None:
    """Register Torch's native library directory on platforms that support it."""
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return

    torch_lib = installation_path / "torch" / "lib"
    if not torch_lib.is_dir():
        raise TorchRuntimeError(_("The external Torch installation is missing its native library directory: {}.").format(torch_lib))

    try:
        _dll_directories.append(os.add_dll_directory(str(torch_lib)))
    except OSError as error:
        raise TorchRuntimeError(_("Unable to register Torch native libraries from '{}': {}.").format(torch_lib, error)) from error


def PrepareTorchRuntime(installation_directory : str|None) -> None:
    """Prepare an optional external Torch path before deferred Torch imports.

    The external path is appended, preserving bundled-module precedence. Python's
    normal site initialization is deliberately not used, so external ``.pth`` files
    are never executed. A changed runtime after Torch was imported requires restart.
    """
    global _configured_path

    requested = (installation_directory or "").strip()
    if not requested:
        if _configured_path is not None:
            raise TorchRuntimeError(_(
                "The external Torch installation setting was cleared after Torch runtime setup. "
                "Restart the application to apply that change."
            ))
        return

    installation_path = _select_installation_path(requested)
    _validate_frozen_compatibility()
    _validate_process_compatibility(installation_path)

    loaded_torch = sys.modules.get("torch")
    if loaded_torch is not None:
        loaded_path = Path(str(getattr(loaded_torch, "__file__", ""))).resolve()
        if installation_path not in loaded_path.parents:
            raise TorchRuntimeError(_(
                "Torch is already loaded from '{}'. Changing the Torch installation requires restarting the application."
            ).format(loaded_path))

    if _configured_path is not None and _configured_path != installation_path:
        raise TorchRuntimeError(_(
            "A different external Torch installation was already selected. Restart the application after changing Torch installation settings."
        ))

    if str(installation_path) not in sys.path:
        sys.path.append(str(installation_path))
    _register_native_libraries(installation_path)
    _configured_path = installation_path
    logging.debug("Prepared external Torch runtime from %s", installation_path)
