import importlib.util
import sys
import unittest
from importlib import metadata

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Transcription.Torch.QwenRuntime import (
    QWEN_ASR_DISTRIBUTION,
    QWEN_ASR_REQUIREMENT,
    QWEN_ASR_UNUSED_DEPENDENCIES,
    ReadQwenAsrDependencies,
    RequirementName,
)


@unittest.skipUnless(importlib.util.find_spec('qwen_asr'), 'qwen-asr is not installed')
class TestInstalledQwenRuntime(LoggedTestCase):
    """The development environment's qwen-asr matches what local transcription setup installs."""

    def test_installed_qwen_asr_is_the_pinned_release(self) -> None:
        """The development environment runs the qwen-asr release that local transcription setup installs."""
        version = metadata.version(QWEN_ASR_DISTRIBUTION)

        self.assertLoggedEqual("qwen-asr requirement", QWEN_ASR_REQUIREMENT, f"{QWEN_ASR_DISTRIBUTION}=={version}")

    def test_installed_qwen_asr_dependencies_exclude_demo_apps(self) -> None:
        """The installed qwen-asr's runtime dependencies include its model stack and none of the demo app packages."""
        dependencies = ReadQwenAsrDependencies(sys.path) or []
        names = {RequirementName(dependency) for dependency in dependencies}

        self.assertLoggedIn("transformers is a dependency", 'transformers', names)
        self.assertLoggedEqual("demo app packages", set(), names & QWEN_ASR_UNUSED_DEPENDENCIES)
