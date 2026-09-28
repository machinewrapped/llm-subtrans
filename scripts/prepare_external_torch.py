"""Prepare and validate an external Torch location for frozen Qwen builds."""

import argparse
import json
import logging
from pathlib import Path
import subprocess
import sys

from PySubtrans.Transcription.Torch.Validation import (
    METADATA_FILENAME,
    OFFICIAL_PYTORCH_SELECTOR,
    BuildCurrentCompatibility,
    CheckCompatibility,
    FindTorchSitePackages,
    FindVenvPython,
    GetPythonAbi,
    ProbeVenvCompatibility,
    ReadCompatibilityMetadata,
)


def BuildCompatibilityMetadata() -> dict[str, object]:
    """Return compatibility data derived from the active Python interpreter."""
    compatibility = BuildCurrentCompatibility()
    python_abi = GetPythonAbi()
    version = sys.version_info

    return {
        "schema_version": 1,
        "kind": "llm-subtrans-frozen-python-compatibility",
        "python_abi": python_abi,
        "python_version": f"{version.major}.{version.minor}",
        "os": compatibility["os"],
        "architecture": compatibility["architecture"],
        "python": {
            "implementation": sys.implementation.name,
            "version": f"{version.major}.{version.minor}.{version.micro}",
            "abi": python_abi,
            "cache_tag": sys.implementation.cache_tag,
        },
        "platform": {
            "os": compatibility["os"],
            "sys_platform": sys.platform,
            "architecture": compatibility["architecture"],
            "pointer_bits": compatibility["pointer_bits"],
        },
        "compatibility": compatibility,
        "torch": {
            "installation": "external",
            "package_policy": "user-installed-complete-runtime",
        },
        "pytorch_selector": OFFICIAL_PYTORCH_SELECTOR,
    }


def PrepareExternalTorch(
    output_directory : str|Path,
    frozen_metadata_path : str|Path,
) -> dict[str, object]:
    """Prepare an empty external location and print official install guidance.

    This function checks the frozen target before creating layout and metadata. It never
    copies, installs, downloads, or reconstructs Torch packages. The user must
    install a complete compatible Torch venv using the official selector.
    """
    output_root = Path(output_directory).expanduser().resolve()
    frozen_metadata = ReadCompatibilityMetadata(frozen_metadata_path)
    python_executable = FindVenvPython(output_root)
    probed = ProbeVenvCompatibility(python_executable) if python_executable is not None else None
    actual = probed if probed is not None else BuildCurrentCompatibility()
    CheckCompatibility(actual, _get_compatibility_section(frozen_metadata))
    output_root.mkdir(parents=True, exist_ok=True)
    _GetSitePackagesDirectory(output_root, create=True)

    metadata = frozen_metadata
    _WriteMetadata(output_root / METADATA_FILENAME, metadata)

    logging.info("Prepared external Torch location: %s", output_root)
    logging.info("Install a complete compatible Torch environment using the command selected at:")
    logging.info(OFFICIAL_PYTORCH_SELECTOR)
    logging.info("Point Qwen Local at the complete venv root after installation.")
    return metadata


def ValidateExternalTorch(installation_directory : str|Path, frozen_metadata_path : str|Path) -> Path:
    """Check Torch directory presence and interpreter compatibility, without importing Torch."""
    frozen_metadata = ReadCompatibilityMetadata(frozen_metadata_path)
    installation_root = Path(installation_directory).expanduser().resolve()
    site_packages = _GetSitePackagesDirectory(installation_root, create=False)
    if not (site_packages / "torch").is_dir():
        raise RuntimeError(
            "The external location does not contain a 'torch' package directory. "
            f"Install the complete hardware-appropriate environment selected at {OFFICIAL_PYTORCH_SELECTOR}."
        )

    python_executable = FindVenvPython(installation_root)
    if python_executable is None:
        raise RuntimeError(
            "The external Torch location must be a complete venv root containing its Python executable."
        )

    actual = ProbeVenvCompatibility(python_executable)
    if actual is None:
        raise RuntimeError(
            f"Unable to probe the Python interpreter at {python_executable}."
        )
    CheckCompatibility(actual, _get_compatibility_section(frozen_metadata))

    logging.info("Torch directory present; interpreter matches frozen metadata: %s", installation_root)
    logging.info("Torch import, native dependencies, and accelerator availability have not been tested.")
    return installation_root


def _get_compatibility_section(metadata : dict[str, object]) -> dict[str, object]:
    """Extract the validated compatibility dict from full metadata."""
    compatibility = metadata["compatibility"]
    if not isinstance(compatibility, dict):
        raise ValueError("Missing compatibility section in metadata.")
    return compatibility



def WriteCompatibilityMetadata(metadata_path : str|Path) -> dict[str, object]:
    """Write compatibility metadata without creating or copying a runtime."""
    metadata = BuildCompatibilityMetadata()
    resolved_path = Path(metadata_path).expanduser().resolve()
    _WriteMetadata(resolved_path, metadata)
    logging.info("Frozen Python compatibility metadata: %s", resolved_path)
    return metadata


def main(arguments : list[str]|None = None) -> int:
    """Run metadata-only, preparation, or validation mode."""
    # When invoked as a subprocess (e.g. from makedistro) there is no pre-existing
    # logging configuration, so set up a clean stdout handler. basicConfig() is a
    # no-op when handlers are already present, so test runners that route logging to
    # a file are unaffected.
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(message)s')
    parser = argparse.ArgumentParser(
        description=(
            "Prepare or validate an external Torch location without copying or downloading packages. "
            "Use the official PyTorch selector for installation."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--metadata-only",
        action="store_true",
        help="Write compatibility metadata only; copy no Torch files.",
    )
    mode.add_argument(
        "--prepare-external-dir",
        metavar="PATH",
        help="Create an empty external venv/site-packages location and print install guidance.",
    )
    mode.add_argument(
        "--validate-external-dir",
        metavar="PATH",
        help="Check Torch directory presence and interpreter compatibility in a user-installed venv.",
    )
    parser.add_argument(
        "--metadata-path",
        help="Output JSON path for --metadata-only.",
    )
    parser.add_argument("--frozen-metadata", help="Required frozen application's JSON for preparation and validation.")
    parsed = parser.parse_args(arguments)

    try:
        if parsed.metadata_only:
            if parsed.frozen_metadata:
                parser.error("--frozen-metadata is not used with --metadata-only")
            if not parsed.metadata_path:
                parser.error("--metadata-only requires --metadata-path")
            WriteCompatibilityMetadata(parsed.metadata_path)
        else:
            if parsed.metadata_path:
                parser.error("--metadata-path is only used with --metadata-only")
            if not parsed.frozen_metadata:
                parser.error("External setup requires --frozen-metadata from the frozen application")
            if parsed.prepare_external_dir:
                PrepareExternalTorch(parsed.prepare_external_dir, parsed.frozen_metadata)
            else:
                ValidateExternalTorch(parsed.validate_external_dir, parsed.frozen_metadata)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"Unable to prepare or validate external Torch: {error}", file=sys.stderr)
        return 1
    return 0


def _GetSitePackagesDirectory(root : Path, create : bool) -> Path:
    """Resolve a runtime layout supported by TorchRuntime.

    For lookup (create=False), delegates to find_torch_site_packages first,
    then falls back to glob-based discovery for venvs with non-standard Python
    versions.  For creation, picks the best directory layout to create.
    """
    # Try the standard candidates via the shared module
    found = FindTorchSitePackages(root)
    if found is not None:
        return found

    # Glob-based fallback for venvs whose Python version differs from ours
    for candidate in sorted(root.glob("lib/python*/site-packages")):
        if (candidate / "torch").is_dir():
            return candidate.resolve()

    if not create:
        raise RuntimeError("The external Torch location has no supported site-packages directory.")

    posix_paths = sorted(root.glob("lib/python*/site-packages"))
    if posix_paths:
        destination = posix_paths[0]
    elif (root / "Lib").is_dir():
        destination = root / "Lib" / "site-packages"
    else:
        destination = root / "site-packages"
    destination.mkdir(parents=True, exist_ok=True)
    return destination.resolve()



def _WriteMetadata(metadata_path : Path, metadata : dict[str, object]) -> None:
    """Write deterministic UTF-8 compatibility metadata."""
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
