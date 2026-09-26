import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Transcription.Torch.QwenRuntime import (
    HasQwenRuntime,
    NeedsQwenRuntime,
    ReadQwenAsrDependencies,
    RequirementName,
)

_MODULE = 'PySubtrans.Transcription.Torch.QwenRuntime'
_SITE_PACKAGES = Path('/torch-env/Lib/site-packages')

# qwen-asr's requirements as the tests declare them: one needed, one only for its demo apps, one only for an extra, one platform-specific
_QWEN_ASR_REQUIRES = ['transformers==4.57.6', 'gradio', 'vllm==0.14.0; extra == "vllm"', 'soundfile; sys_platform == "win32"']


class TestQwenAsrDependencies(LoggedTestCase):
    """The Qwen runtime installs the dependencies qwen-asr declares, minus the ones only its demo apps use."""

    def test_dependencies_leave_out_demo_apps_and_extras(self) -> None:
        """Demo-only and extra-only requirements are dropped, and the rest keep their pins and markers."""
        with patch(f'{_MODULE}.metadata.distributions', return_value=[SimpleNamespace(requires=_QWEN_ASR_REQUIRES)]):
            dependencies = ReadQwenAsrDependencies([str(_SITE_PACKAGES)])

        self.assertLoggedEqual("runtime dependencies", ['transformers==4.57.6', 'soundfile; sys_platform == "win32"'], dependencies)

    def test_missing_qwen_asr_has_no_dependencies(self) -> None:
        """Without qwen-asr installed there is nothing to read the dependencies from."""
        with patch(f'{_MODULE}.metadata.distributions', return_value=[]):
            self.assertLoggedIsNone("dependencies", ReadQwenAsrDependencies([str(_SITE_PACKAGES)]))

    def test_requirement_name_normalises_spelling(self) -> None:
        """Names compare equal whatever their case or separators, with version specifiers removed."""
        self.assertLoggedEqual("normalised name", 'qwen-asr', RequirementName('Qwen_ASR==0.0.6'))


class TestQwenRuntimeDetection(LoggedTestCase):
    """Torch environments are checked for the Qwen runtime that packaged builds import from them."""

    def _has_runtime(self, dependencies : list[str]|None, installed : set[str]) -> tuple[bool, list[str]]:
        """Check an environment whose qwen-asr declares these dependencies, with these distributions installed.
        Returns the result and the distributions that were looked up."""
        looked_up : list[str] = []

        def is_installed(name : str, search_path : list[str]) -> bool:
            looked_up.append(name)
            return name in installed

        with patch(f'{_MODULE}.FindTorchSitePackages', return_value=_SITE_PACKAGES), \
                patch(f'{_MODULE}.ReadQwenAsrDependencies', return_value=dependencies), \
                patch(f'{_MODULE}._IsInstalled', side_effect=is_installed):
            return HasQwenRuntime(Path('/torch-env')), looked_up

    def test_qwen_asr_with_dependencies_is_complete(self) -> None:
        """qwen-asr beside Torch with the dependencies it needs is the Qwen runtime."""
        has_runtime, _looked_up = self._has_runtime(['transformers==4.57.6', 'librosa'], {'transformers', 'librosa'})

        self.assertLoggedTrue("runtime found", has_runtime)

    def test_qwen_asr_without_dependencies_is_incomplete(self) -> None:
        """Setup interrupted after installing qwen-asr leaves an environment that still needs the runtime installed."""
        has_runtime, _looked_up = self._has_runtime(['transformers==4.57.6', 'librosa'], {'librosa'})

        self.assertLoggedFalse("runtime not found", has_runtime)

    def test_torch_only_environment_has_no_runtime(self) -> None:
        """An environment set up for 1.7.0 has Torch alone."""
        has_runtime, _looked_up = self._has_runtime(None, set())

        self.assertLoggedFalse("runtime not found", has_runtime)

    def test_platform_specific_dependencies_are_not_checked(self) -> None:
        """A dependency with an environment marker may not apply here, so it is not required."""
        has_runtime, looked_up = self._has_runtime(['transformers==4.57.6', 'soundfile; sys_platform == "win32"'], {'transformers'})

        self.assertLoggedTrue("runtime found", has_runtime)
        self.assertLoggedEqual("distributions looked up", ['transformers'], looked_up)

    def test_frozen_build_needs_runtime_it_lacks(self) -> None:
        """A packaged build only finds the Qwen runtime in the Torch environment."""
        with patch(f'{_MODULE}.HasQwenRuntime', return_value=False), \
                patch.object(sys, 'frozen', True, create=True):
            self.assertLoggedTrue("runtime needed", NeedsQwenRuntime(Path('/torch-env')))

    def test_frozen_build_needs_nothing_when_runtime_installed(self) -> None:
        """A complete environment needs nothing more installed."""
        with patch(f'{_MODULE}.HasQwenRuntime', return_value=True), \
                patch.object(sys, 'frozen', True, create=True):
            self.assertLoggedFalse("runtime not needed", NeedsQwenRuntime(Path('/torch-env')))

    def test_source_run_uses_its_own_qwen_runtime(self) -> None:
        """A source run with qwen-asr installed locally does not need it in the Torch environment."""
        with patch(f'{_MODULE}.HasQwenRuntime', return_value=False):
            with patch(f'{_MODULE}.importlib.util.find_spec', return_value=object()):
                self.assertLoggedFalse("runtime not needed", NeedsQwenRuntime(Path('/torch-env')))

            with patch(f'{_MODULE}.importlib.util.find_spec', return_value=None):
                self.assertLoggedTrue("runtime needed without a local copy", NeedsQwenRuntime(Path('/torch-env')))
