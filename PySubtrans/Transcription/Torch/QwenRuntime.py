"""Requirements and discovery for the Qwen runtime in an external Torch environment.

Packaged builds do not bundle qwen-asr or its dependencies.
Local transcription setup installs them into the same environment as Torch, and they are imported from there.
Pure logic with no Torch or Qt imports.
"""

import importlib.util
import sys
from importlib import metadata
from pathlib import Path

import regex

from PySubtrans.Transcription.Torch.Validation import FindTorchSitePackages

QWEN_ASR_DISTRIBUTION = 'qwen-asr'
QWEN_ASR_MODULE = 'qwen_asr'

# The qwen-asr release the runtime is installed from; its dependency pins come from its own metadata
QWEN_ASR_REQUIREMENT = 'qwen-asr==0.0.6'

# qwen-asr dependencies used only by its demo apps and server, which the runtime leaves out
QWEN_ASR_UNUSED_DEPENDENCIES = {'gradio', 'flask', 'sox', 'qwen-omni-utils', 'pytz'}

_REQUIREMENT_NAME_PATTERN = regex.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*')
_EXTRA_MARKER_PATTERN = regex.compile(r';.*\bextra\s*==')


def RequirementName(requirement : str) -> str:
    """Return the normalised distribution name of a pip requirement."""
    match = _REQUIREMENT_NAME_PATTERN.match(requirement.strip())
    name = match.group(0) if match else requirement.strip()
    return regex.sub(r'[-_.]+', '-', name).lower()


def ReadQwenAsrDependencies(search_path : list[str]) -> list[str]|None:
    """
    Return the dependencies an installed qwen-asr declares, minus the unused ones and those only its extras need.
    Requirements keep their version and environment markers, so pip applies them as qwen-asr intends.
    Returns None if qwen-asr is not installed on the search path.
    """
    distribution = next(iter(metadata.distributions(name=QWEN_ASR_DISTRIBUTION, path=search_path)), None)
    if distribution is None:
        return None

    return [
        requirement for requirement in distribution.requires or []
        if not _EXTRA_MARKER_PATTERN.search(requirement)
        and RequirementName(requirement) not in QWEN_ASR_UNUSED_DEPENDENCIES
    ]


def QwenAsrPipArguments() -> list[str]:
    """
    The pip arguments for the first part of the Qwen runtime install: qwen-asr without its dependencies.
    Its dependencies follow once it is installed, from QwenDependencyPipArguments.
    """
    return ['install', '--no-deps', QWEN_ASR_REQUIREMENT]


def QwenDependencyPipArguments(search_path : list[str]) -> list[str]|None:
    """
    The pip arguments for the second part of the Qwen runtime install: the dependencies of the qwen-asr on the search path.
    Returns None if qwen-asr is not installed there.
    """
    dependencies = ReadQwenAsrDependencies(search_path)
    if dependencies is None:
        return None

    # pip would report the demo app packages left out as missing dependencies of qwen-asr, which reads as a failed install
    return ['install', '--no-warn-conflicts', *dependencies]


def HasQwenRuntime(root : Path) -> bool:
    """
    Whether the Torch environment at *root* has qwen-asr and the dependencies it declares installed beside Torch.
    qwen-asr is installed before its dependencies, so on its own it may be left from an interrupted setup.
    Requirements with environment markers are not checked, since they may not apply here.
    """
    site_packages = FindTorchSitePackages(root)
    if site_packages is None:
        return False

    search_path = [str(site_packages)]
    dependencies = ReadQwenAsrDependencies(search_path)
    if dependencies is None:
        return False

    return all(_IsInstalled(RequirementName(dependency), search_path) for dependency in dependencies if ';' not in dependency)


def NeedsQwenRuntime(root : Path) -> bool:
    """
    Whether the Qwen runtime has to be installed into the Torch environment at *root*.
    Packaged builds only find it there.
    A source run can import it from its own environment instead.
    """
    if HasQwenRuntime(root):
        return False

    return bool(getattr(sys, 'frozen', False)) or importlib.util.find_spec(QWEN_ASR_MODULE) is None


def _IsInstalled(distribution_name : str, search_path : list[str]) -> bool:
    """Whether a distribution is installed on the search path."""
    return next(iter(metadata.distributions(name=distribution_name, path=search_path)), None) is not None
