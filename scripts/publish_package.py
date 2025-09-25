#!/usr/bin/env python3
"""
PySubtrans Package Publisher

This script builds and publishes the PySubtrans package to PyPI or TestPyPI.

Usage:
    # Publish to PyPI (production)
    python scripts/publish_package.py

    # Publish to TestPyPI (for testing)
    python scripts/publish_package.py --repository testpypi

    # Build only (skip upload)
    python scripts/publish_package.py --skip-upload

    # Skip confirmation prompts
    python scripts/publish_package.py --yes

Prerequisites:
    - pip install build twine
    - Configure ~/.pypirc with your API tokens for PyPI/TestPyPI

The script will:
1. Generate a dedicated pyproject.toml for the PySubtrans package
2. Display package configuration summary
3. Clean previous build artifacts
4. Build wheel and source distributions
5. Upload to the specified repository (unless --skip-upload)
"""
from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib  # type: ignore

PACKAGE_NAME = "pysubtrans"
PACKAGE_DESCRIPTION = "Core subtitle translation toolkit used by LLM-Subtrans"
HOMEPAGE_URL = "https://github.com/machinewrapped/llm-subtrans"
DOCUMENTATION_URL = "https://github.com/machinewrapped/llm-subtrans/blob/main/PySubtrans/README.md"
ISSUES_URL = "https://github.com/machinewrapped/llm-subtrans/issues"


def ParseArguments() -> argparse.Namespace:
    """Parse command line arguments for the publish workflow."""
    parser = argparse.ArgumentParser(description="Build and publish the PySubtrans package")
    parser.add_argument("--yes", action="store_true", help="Assume yes for all confirmation prompts")
    parser.add_argument("--skip-upload", action="store_true", help="Skip the upload step")
    parser.add_argument("--repository", type=str, default=None, help="Named repository configured in ~/.pypirc (e.g. testpypi)")
    return parser.parse_args()


def LoadToml(path: Path) -> dict[str, Any]:
    """Load a TOML file into a dictionary."""
    with path.open("rb") as handle:
        return tomllib.load(handle)


def FormatTomlList(items: list[str], indent: int = 4) -> str:
    """Format a list of strings as a TOML array."""
    if not items:
        return "[]"

    indent_str = " " * indent
    joined_items = ",\n".join(f'{indent_str}"{item}"' for item in items)
    closing_indent = " " * max(indent - 4, 0)
    return f"[\n{joined_items}\n{closing_indent}]"


def WritePackageToml(
    path: Path,
    version: str,
    dependencies: list[str],
    optional_dependencies: dict[str, list[str]],
    requires_python: str,
    package_dir: Path,
) -> None:
    """Write the dedicated PySubtrans pyproject file."""
    dependencies_block = FormatTomlList(dependencies)

    # Dynamically discover all packages (directories with __init__.py)
    packages = ["PySubtrans"]  # Root package

    # Find all subdirectory packages (excluding UnitTests)
    for init_file in package_dir.rglob("__init__.py"):
        if init_file.parent != package_dir:  # Skip the root __init__.py
            relative_path = init_file.parent.relative_to(package_dir)
            # Convert path separators to dots for Python package names
            package_name = f"PySubtrans.{'.'.join(relative_path.parts)}"
            # Exclude unit tests from distribution
            if not package_name.startswith("PySubtrans.UnitTests"):
                packages.append(package_name)

    packages.sort()
    packages_block = FormatTomlList(packages)

    lines: list[str] = [
        "[build-system]",
        'requires = ["setuptools>=61.0"]',
        'build-backend = "setuptools.build_meta"',
        "",
        "[project]",
        f'name = "{PACKAGE_NAME}"',
        f'version = "{version}"',
        f'description = "{PACKAGE_DESCRIPTION}"',
        'readme = "README.md"',
        f'requires-python = "{requires_python}"',
        'license = {file = "LICENSE"}',
        f"dependencies = {dependencies_block}",
        "",
    ]

    if optional_dependencies:
        lines.append("[project.optional-dependencies]")
        for extra, packages in optional_dependencies.items():
            lines.append(f"{extra} = {FormatTomlList(packages)}")
        lines.append("")

    lines.extend(
        [
            "[project.urls]",
            f'Homepage = "{HOMEPAGE_URL}"',
            f'Documentation = "{DOCUMENTATION_URL}"',
            f'Source = "{HOMEPAGE_URL}"',
            f'Issues = "{ISSUES_URL}"',
            "",
            "[tool.setuptools]",
            f"packages = {packages_block}",
            'package-dir = {"PySubtrans" = "."}',
            "",
        ]
    )

    content = "\n".join(lines).rstrip() + "\n"
    path.write_text(content, encoding="utf-8")


def PrintSummary(version: str, dependencies: list[str], optional: dict[str, list[str]]) -> None:
    """Display the key package metadata before building."""
    print("PySubtrans package configuration")
    print(f"  Version: {version}")
    print("  Dependencies:")
    for dependency in dependencies:
        print(f"    - {dependency}")

    if optional:
        print("  Optional extras:")
        for name, packages in optional.items():
            package_list = ", ".join(packages)
            print(f"    - {name}: {package_list}")


def Confirm(prompt: str, assume_yes: bool = False) -> bool:
    """Ask the user for confirmation."""
    if assume_yes:
        print(f"{prompt} [auto-yes]")
        return True

    try:
        response = input(f"{prompt} [y/N]: ").strip().lower()
    except EOFError:
        return False

    return response in {"y", "yes"}


def EnsureBuildTools(upload_requested: bool) -> None:
    """Validate that build and upload tooling is available."""
    if importlib.util.find_spec("build") is None:
        raise ModuleNotFoundError(
            "The 'build' package is required. Install it with 'pip install build'."
        )

    if upload_requested and importlib.util.find_spec("twine") is None:
        raise ModuleNotFoundError(
            "The 'twine' package is required for uploads. Install it with 'pip install twine'."
        )


def CleanBuildArtifacts(package_dir: Path) -> None:
    """Remove previous build artefacts to ensure a clean build."""
    for folder_name in ("build", "dist"):
        folder = package_dir / folder_name
        if folder.exists():
            shutil.rmtree(folder)

    for egg_info in package_dir.glob("*.egg-info"):
        if egg_info.is_dir():
            shutil.rmtree(egg_info)
        else:
            egg_info.unlink()


def BuildPackage(package_dir: Path) -> None:
    """Build the wheel and source distribution for PySubtrans."""
    command = [sys.executable, "-m", "build"]
    subprocess.run(command, cwd=package_dir, check=True)


def UploadPackage(dist_dir: Path, repository: str|None = None) -> None:
    """Upload the built distributions using twine."""
    if not dist_dir.exists():
        raise FileNotFoundError(f"Distribution directory {dist_dir} does not exist")

    distributions = sorted(dist_dir.glob("*"))
    if not distributions:
        raise FileNotFoundError("No distribution files found to upload")

    command = [sys.executable, "-m", "twine", "upload"]
    if repository:
        command.extend(["--repository", repository])

    command.extend(str(path) for path in distributions)
    subprocess.run(command, check=True)


def GetPackageVersion(package_dir: Path) -> str:
    """Extract version from PySubtrans/version.py."""
    version_file = package_dir / "version.py"
    if not version_file.exists():
        raise FileNotFoundError(f"Version file {version_file} does not exist")

    # Read and parse the version file
    version_content = version_file.read_text(encoding="utf-8")
    for line in version_content.splitlines():
        line = line.strip()
        if line.startswith("__version__"):
            # Extract version string from __version__ = "vX.Y.Z" format
            version = line.split("=", 1)[1].strip().strip('"').strip("'")
            # Remove 'v' prefix if present
            if version.startswith('v'):
                version = version[1:]
            return version

    raise ValueError("Could not find __version__ in version.py")


def Main() -> None:
    """Entrypoint for the publish helper."""
    args = ParseArguments()

    project_root = Path(__file__).resolve().parent.parent
    root_pyproject = project_root / "pyproject.toml"
    package_dir = project_root / "PySubtrans"
    package_pyproject = package_dir / "pyproject.toml"

    if not root_pyproject.exists():
        raise FileNotFoundError("Unable to locate the root pyproject.toml")

    if not package_dir.exists():
        raise FileNotFoundError("PySubtrans directory does not exist")

    root_config = LoadToml(root_pyproject)
    project_config = root_config.get("project", {})

    version = GetPackageVersion(package_dir)
    requires_python = str(project_config.get("requires-python", ">=3.10"))
    dependencies = list(project_config.get("dependencies", []))

    optional = {
        name: list(values)
        for name, values in project_config.get("optional-dependencies", {}).items()
        if name != "gui"
    }

    WritePackageToml(package_pyproject, version, dependencies, optional, requires_python, package_dir)
    PrintSummary(version, dependencies, optional)

    try:
        EnsureBuildTools(upload_requested=not args.skip_upload)
    except ModuleNotFoundError as error:
        print(error)
        return

    if not Confirm("Proceed with build?", assume_yes=args.yes):
        print("Build cancelled")
        return

    CleanBuildArtifacts(package_dir)

    try:
        BuildPackage(package_dir)
    except subprocess.CalledProcessError as error:
        print(f"Build failed with exit code {error.returncode}")
        raise

    print(f"Build complete. Distributions written to {package_dir / 'dist'}")

    if args.skip_upload:
        print("Upload skipped as requested")
        return

    if Confirm("Upload package with twine?", assume_yes=args.yes):
        try:
            UploadPackage(package_dir / "dist", repository=args.repository)
        except subprocess.CalledProcessError as error:
            print(f"Upload failed with exit code {error.returncode}")
            raise


if __name__ == "__main__":
    Main()
