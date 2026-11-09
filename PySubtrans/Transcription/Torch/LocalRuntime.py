"""What the setup wizard needs to know about each local transcription runtime.

Each runtime has its own environment, so their dependency versions cannot conflict.
Pure logic with no Torch or Qt imports.
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import ConfigActionOption
from PySubtrans.Transcription.Torch.Discovery import FindExistingTorch
from PySubtrans.Transcription.Torch.MossRuntime import (
    HasMossRuntime,
    MOSS_ENVIRONMENT_NAME,
    MOSS_REQUIREMENT,
    MossDependencyPipArguments,
    MossPipArguments,
)
from PySubtrans.Transcription.Torch.QwenRuntime import (
    HasQwenRuntime,
    NeedsQwenRuntime,
    QWEN_ASR_REQUIREMENT,
    QWEN_ENVIRONMENT_NAME,
    QwenAsrPipArguments,
    QwenDependencyPipArguments,
)


class TorchConfigOption(ConfigActionOption):
    """Sentinel for the Torch and Qwen installation directory setting."""
    label = _("Set up Qwen...")


class MossConfigOption(ConfigActionOption):
    """Sentinel for the MOSS installation directory setting."""
    label = _("Set up MOSS...")


@dataclass(frozen=True)
class LocalRuntime:
    """A local transcription runtime installed into its own Torch environment."""
    # Short name used in the wizard, e.g. "Qwen"
    name : str
    # The provider the runtime serves, e.g. "Qwen Local"
    provider_name : str
    # Default environment folder beside the application
    environment_name : str
    # The settings option that opens the wizard for this runtime
    setup_option : type[ConfigActionOption]
    # The runtime's own package, as the wizard names it and as pip installs it
    package_name : str
    package_requirement : str
    # Approximate disk usage of the runtime on its own, when adding it to an environment that has Torch
    runtime_size : str
    # Locates an existing environment to offer, or None
    find_existing : Callable[[], str|None]
    # Whether an environment has this runtime installed
    has_runtime : Callable[[Path], bool]
    # Whether an environment needs this runtime installed before it can be used
    needs_runtime : Callable[[Path], bool]
    # pip arguments for the package without its dependencies
    package_pip_arguments : Callable[[], list[str]]
    # pip arguments for the dependencies, given the environment's site-packages, or None if they cannot be read
    dependency_pip_arguments : Callable[[list[str]], list[str]|None]


QWEN_RUNTIME = LocalRuntime(
    name="Qwen",
    provider_name="Qwen Local",
    environment_name=QWEN_ENVIRONMENT_NAME,
    setup_option=TorchConfigOption,
    package_name="qwen-asr",
    package_requirement=QWEN_ASR_REQUIREMENT,
    runtime_size=_("~600 MB"),
    find_existing=partial(FindExistingTorch, QWEN_ENVIRONMENT_NAME, HasQwenRuntime),
    has_runtime=HasQwenRuntime,
    needs_runtime=NeedsQwenRuntime,
    package_pip_arguments=QwenAsrPipArguments,
    dependency_pip_arguments=QwenDependencyPipArguments,
)

MOSS_RUNTIME = LocalRuntime(
    name="MOSS",
    provider_name="MOSS Local",
    environment_name=MOSS_ENVIRONMENT_NAME,
    setup_option=MossConfigOption,
    package_name="MOSS-Transcribe-Diarize",
    package_requirement=MOSS_REQUIREMENT,
    runtime_size=_("~600 MB"),
    find_existing=partial(FindExistingTorch, MOSS_ENVIRONMENT_NAME, HasMossRuntime),
    has_runtime=HasMossRuntime,
    needs_runtime=lambda root: not HasMossRuntime(root),
    package_pip_arguments=MossPipArguments,
    dependency_pip_arguments=lambda _search_path: MossDependencyPipArguments(),
)

LOCAL_RUNTIMES : list[LocalRuntime] = [QWEN_RUNTIME, MOSS_RUNTIME]


def LocalRuntimeForOption(option : type) -> LocalRuntime|None:
    """The runtime whose setup a settings option opens, or None if it is not a runtime setup option."""
    return next((runtime for runtime in LOCAL_RUNTIMES if issubclass(option, runtime.setup_option)), None)


def OtherRuntimesIn(runtime : LocalRuntime, root : Path) -> list[LocalRuntime]:
    """Other runtimes installed in an environment, which installing this one could break."""
    return [other for other in LOCAL_RUNTIMES if other.name != runtime.name and other.has_runtime(root)]
