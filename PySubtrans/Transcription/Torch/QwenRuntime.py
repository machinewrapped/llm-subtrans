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


def HasQwenRuntime(root : Path) -> bool:
    """Whether the Torch environment at *root* has qwen-asr installed beside Torch."""
    site_packages = FindTorchSitePackages(root)
    return site_packages is not None and (site_packages / QWEN_ASR_MODULE).is_dir()


def NeedsQwenRuntime(root : Path) -> bool:
    """
    Whether the Qwen runtime has to be installed into the Torch environment at *root*.
    Packaged builds only find it there.
    A source run can import it from its own environment instead.
    """
    if HasQwenRuntime(root):
        return False

    return bool(getattr(sys, 'frozen', False)) or importlib.util.find_spec(QWEN_ASR_MODULE) is None
