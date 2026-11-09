"""Requirements and discovery for the MOSS runtime in its own environment.

MOSS needs Transformers 5, and qwen-asr pins Transformers 4, so the two runtimes cannot share an environment.
MOSS is not on PyPI, so the runtime installs its package from a GitHub archive at a fixed commit.
Pure logic with no Torch or Qt imports.
"""

from pathlib import Path

from PySubtrans.Transcription.Torch.Requirements import IsInstalled, RequirementName
from PySubtrans.Transcription.Torch.Validation import FindTorchSitePackages

MOSS_DISTRIBUTION = 'moss-transcribe-diarize'
# Default environment folder beside the application, for source installs
MOSS_ENVIRONMENT_NAME = 'envmoss'

MOSS_COMMIT = '79c675f0670cc2f824bcbcdd98263704f40f1f7e'
MOSS_REQUIREMENT = f'{MOSS_DISTRIBUTION} @ https://github.com/OpenMOSS/MOSS-Transcribe-Diarize/archive/{MOSS_COMMIT}.zip'

MOSS_MODEL = 'OpenMOSS-Team/MOSS-Transcribe-Diarize'
MOSS_MODEL_REVISION = '10304d926740cf5a5cee05a268086e3265197910'

# The model's context is 40,960 tokens, and audio takes about 12.5 of them per second.
# Chunks up to this length leave room for the transcript.
MOSS_MAX_CHUNK_SECONDS = 1200.0

# The package's dependencies at MOSS_COMMIT, without the fastapi, uvicorn and python-multipart its web app needs
MOSS_DEPENDENCIES = [
    'transformers>=5.6.0,<6.0.0',
    'safetensors>=0.6.2',
    'numpy>=1.26,<3',
    'av>=14.0',
    'librosa>=0.11.0',
    'numba>=0.61.0',
    'soundfile>=0.12',
    'soxr>=0.5',
    'packaging',
]


def MossPipArguments() -> list[str]:
    """
    The pip arguments for the first part of the MOSS runtime install: the package without its dependencies.
    MossDependencyPipArguments installs the dependencies it needs next.
    """
    return ['install', '--no-deps', MOSS_REQUIREMENT]


def MossDependencyPipArguments() -> list[str]:
    """The pip arguments for the second part of the MOSS runtime install: its dependencies, minus the web app's."""
    # pip would report the web app packages left out as missing dependencies, which reads as a failed install
    return ['install', '--no-warn-conflicts', *MOSS_DEPENDENCIES]


def HasMossRuntime(root : Path) -> bool:
    """
    Whether the environment at *root* has the MOSS package and its dependencies installed beside Torch.
    The package is installed before its dependencies, so on its own it may be left from an interrupted setup.
    """
    site_packages = FindTorchSitePackages(root)
    if site_packages is None:
        return False

    search_path = [str(site_packages)]
    required = [MOSS_DISTRIBUTION, *MOSS_DEPENDENCIES]
    return all(IsInstalled(RequirementName(requirement), search_path) for requirement in required)
