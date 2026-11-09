from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Options import ConfigActionOption
from PySubtrans.Transcription.Torch.LocalRuntime import (
    MOSS_RUNTIME,
    MossConfigOption,
    QWEN_RUNTIME,
    LocalRuntimeForOption,
    OtherRuntimesIn,
)
from PySubtrans.Transcription.Torch.Runtime import TorchConfigOption

_MODULE = 'PySubtrans.Transcription.Torch.LocalRuntime'


class TestLocalRuntimes(LoggedTestCase):
    """Each runtime has its own setup option and environment."""

    def test_setup_option_selects_runtime(self) -> None:
        """A provider's setup button opens the wizard for its own runtime."""
        class OtherOption(ConfigActionOption):
            label = "Other"

        self.assertLoggedIs("Qwen setup", QWEN_RUNTIME, LocalRuntimeForOption(TorchConfigOption))
        self.assertLoggedIs("MOSS setup", MOSS_RUNTIME, LocalRuntimeForOption(MossConfigOption))
        self.assertLoggedIsNone("not a runtime option", LocalRuntimeForOption(OtherOption))

    def test_other_runtimes_found_in_environment(self) -> None:
        """An environment with another runtime is reported, so this one is not installed over it."""
        qwen = replace(QWEN_RUNTIME, has_runtime=Mock(return_value=True))
        moss = replace(MOSS_RUNTIME, has_runtime=Mock(return_value=False))

        with patch(f'{_MODULE}.LOCAL_RUNTIMES', [qwen, moss]):
            self.assertLoggedEqual("Qwen found when installing MOSS", [qwen], OtherRuntimesIn(moss, Path('/env')))
            self.assertLoggedEqual("nothing else found when installing Qwen", [], OtherRuntimesIn(qwen, Path('/env')))
