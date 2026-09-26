import importlib.util
import sys
import tempfile
import unittest
from importlib import metadata
from pathlib import Path
from unittest.mock import patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Transcription.Torch.QwenRuntime import (
    QWEN_ASR_DISTRIBUTION,
    QWEN_ASR_REQUIREMENT,
    QWEN_ASR_UNUSED_DEPENDENCIES,
    HasQwenRuntime,
    NeedsQwenRuntime,
    ReadQwenAsrDependencies,
    RequirementName,
)

QWEN_ASR_INSTALLED = importlib.util.find_spec('qwen_asr') is not None

_QWEN_ASR_METADATA = """Metadata-Version: 2.1
Name: qwen-asr
Version: 0.0.6
Requires-Dist: transformers==4.57.6
Requires-Dist: gradio
Requires-Dist: Qwen_Omni_Utils
Requires-Dist: soundfile; sys_platform == "win32"
Requires-Dist: vllm==0.14.0; extra == "vllm"
"""


def _make_environment(root : Path, packages : list[str]) -> None:
    """Create a Windows-layout venv under root with empty package directories."""
    site_packages = root / 'Lib' / 'site-packages'
    for package in packages:
        (site_packages / package).mkdir(parents=True)


class TestQwenAsrDependencies(LoggedTestCase):
    """The Qwen runtime installs the dependencies qwen-asr declares, minus the ones only its demo apps use."""

    def test_dependencies_leave_out_demo_apps_and_extras(self) -> None:
        """Demo-only and extra-only requirements are dropped, and the rest keep their pins and markers."""
        with tempfile.TemporaryDirectory() as directory:
            dist_info = Path(directory) / 'qwen_asr-0.0.6.dist-info'
            dist_info.mkdir()
            (dist_info / 'METADATA').write_text(_QWEN_ASR_METADATA, encoding='utf-8')

            dependencies = ReadQwenAsrDependencies([directory])

        self.assertLoggedEqual("runtime dependencies", ['transformers==4.57.6', 'soundfile; sys_platform == "win32"'], dependencies)

    def test_missing_qwen_asr_has_no_dependencies(self) -> None:
        """Without qwen-asr installed there is nothing to read the dependencies from."""
        with tempfile.TemporaryDirectory() as directory:
            self.assertLoggedIsNone("dependencies", ReadQwenAsrDependencies([directory]))

    def test_requirement_name_normalises_spelling(self) -> None:
        """Names compare equal whatever their case or separators, with version specifiers removed."""
        self.assertLoggedEqual("normalised name", 'qwen-asr', RequirementName('Qwen_ASR==0.0.6'))

    @unittest.skipUnless(QWEN_ASR_INSTALLED, "qwen-asr is not installed")
    def test_installed_qwen_asr_is_the_pinned_release(self) -> None:
        """The development environment runs the qwen-asr release that local transcription setup installs."""
        version = metadata.version(QWEN_ASR_DISTRIBUTION)

        self.assertLoggedEqual("qwen-asr requirement", QWEN_ASR_REQUIREMENT, f"{QWEN_ASR_DISTRIBUTION}=={version}")

    @unittest.skipUnless(QWEN_ASR_INSTALLED, "qwen-asr is not installed")
    def test_installed_qwen_asr_dependencies_exclude_demo_apps(self) -> None:
        """The installed qwen-asr's runtime dependencies include its model stack and none of the demo app packages."""
        dependencies = ReadQwenAsrDependencies(sys.path) or []
        names = {RequirementName(dependency) for dependency in dependencies}

        self.assertLoggedIn("transformers is a dependency", 'transformers', names)
        self.assertLoggedEqual("demo app packages", set(), names & QWEN_ASR_UNUSED_DEPENDENCIES)


class TestQwenRuntimeDetection(LoggedTestCase):
    """Torch environments are checked for the Qwen runtime that packaged builds import from them."""

    def test_environment_with_qwen_asr_has_runtime(self) -> None:
        """qwen-asr beside Torch counts as the Qwen runtime."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _make_environment(root, ['torch', 'qwen_asr'])

            self.assertLoggedTrue("runtime found", HasQwenRuntime(root))

    def test_torch_only_environment_needs_runtime_in_frozen_build(self) -> None:
        """An environment set up for 1.7.0 has Torch alone, which a packaged build cannot use."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _make_environment(root, ['torch'])

            self.assertLoggedFalse("runtime not found", HasQwenRuntime(root))
            with patch.object(sys, 'frozen', True, create=True):
                self.assertLoggedTrue("runtime needed", NeedsQwenRuntime(root))

    def test_frozen_build_needs_nothing_when_runtime_installed(self) -> None:
        """A complete environment needs nothing more installed."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _make_environment(root, ['torch', 'qwen_asr'])

            with patch.object(sys, 'frozen', True, create=True):
                self.assertLoggedFalse("runtime not needed", NeedsQwenRuntime(root))

    def test_source_run_uses_its_own_qwen_runtime(self) -> None:
        """A source run with qwen-asr installed locally does not need it in the Torch environment."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _make_environment(root, ['torch'])

            with patch('PySubtrans.Transcription.Torch.QwenRuntime.importlib.util.find_spec', return_value=object()):
                self.assertLoggedFalse("runtime not needed", NeedsQwenRuntime(root))

            with patch('PySubtrans.Transcription.Torch.QwenRuntime.importlib.util.find_spec', return_value=None):
                self.assertLoggedTrue("runtime needed without a local copy", NeedsQwenRuntime(root))
