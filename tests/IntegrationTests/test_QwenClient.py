import importlib.util
import unittest

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.SettingsType import SettingsType
from PySubtrans.Transcription.Providers import Provider_QwenLocal

QwenLocalProvider = getattr(Provider_QwenLocal, 'QwenLocalProvider', None)


@unittest.skipUnless(importlib.util.find_spec('qwen_asr'), 'qwen-asr is not installed')
class TestQwenClientIntegration(LoggedTestCase):
    def test_client_construction(self):
        """The installed Qwen SDK can construct a client without loading model weights."""
        assert QwenLocalProvider is not None  # Type narrowing for PyLance
        provider = QwenLocalProvider(SettingsType())
        client = provider.GetTranscriptionClient(SettingsType())

        self.assertLoggedEqual("client type", "QwenLocalClient", type(client).__name__)
        self.assertLoggedEqual("timestamps advertised", True, client.supports_timestamps)

