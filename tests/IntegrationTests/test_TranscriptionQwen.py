import unittest
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import skip_if_debugger_attached
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.Providers.Provider_QwenLocal import parse_qwen_result
import PySubtrans.Transcription.Providers.Provider_QwenLocal as _qwen_module
import PySubtrans.Transcription.Providers.Clients.QwenLocalClient as qwen_module

QwenLocalProvider = getattr(_qwen_module, 'QwenLocalProvider', None)

class TestQwenLocalProvider(LoggedTestCase):
    def setUp(self):
        super().setUp()
        if QwenLocalProvider is None:
            self.skipTest("qwen-asr not installed")

    def test_registered(self):
        """Qwen Local registers when its SDK is present."""
        providers = TranscriptionProvider.get_providers()

        self.assertLoggedIn("qwen present", "Qwen Local", providers)

    def test_options_ungated(self):
        """Keyless local provider always shows the full schema."""
        assert QwenLocalProvider is not None  # Type narrowing for PyLance
        provider = QwenLocalProvider(SettingsType())
        options = provider.GetOptions(provider.settings)

        for key in ("model", "language", "device", "aligner_model", "max_new_tokens", "rate_limit"):
            self.assertLoggedIn(f"{key} option", key, options)
        self.assertLoggedIn("checkpoint", "Qwen/Qwen3-ASR-1.7B", provider.GetAvailableModels())

    def test_advanced_settings_match_schema(self):
        """Advanced keys must exist in the options schema, or filtering silently misses."""
        assert QwenLocalProvider is not None  # Type narrowing for PyLance
        provider = QwenLocalProvider(SettingsType())
        options = provider.GetOptions(provider.settings)

        unknown = [key for key in provider.advanced_settings if key not in options]
        self.assertLoggedEqual("no stale advanced keys", [], unknown)

    def test_validate_needs_no_key(self):
        """Local inference validates without credentials."""
        assert QwenLocalProvider is not None  # Type narrowing for PyLance
        provider = QwenLocalProvider(SettingsType())

        self.assertLoggedEqual("valid by default", True, provider.ValidateSettings())



    def test_information_torch_states(self):
        """Qwen appends install guidance until a device is recorded; CPU notes slowness."""
        assert QwenLocalProvider is not None  # Type narrowing for PyLance
        provider = QwenLocalProvider(SettingsType())

        unknown = provider.GetInformation(ffmpeg_available=True, torch_device="Unknown")
        cuda = provider.GetInformation(ffmpeg_available=True, torch_device="cuda:0")
        cpu = provider.GetInformation(ffmpeg_available=True, torch_device="cpu")

        self.assertLoggedIsNotNone("unknown info", unknown)
        self.assertLoggedIn("install guidance", "pytorch.org", unknown or "")
        self.assertLoggedNotIn("cuda clean", "pytorch.org", cuda or "")
        self.assertLoggedNotIn("cuda slow note", "much slower", cuda or "")
        self.assertLoggedNotIn("cpu install guidance", "pytorch.org", cpu or "")
        self.assertLoggedIn("cpu slow note", "much slower", cpu or "")
        self.assertLoggedIn("cuda line always present", "much faster", cuda or "")

class TestQwenLocalDevice(LoggedTestCase):
    def setUp(self):
        super().setUp()
        if QwenLocalProvider is None:
            self.skipTest("qwen-asr not installed")
        # Warm the lazy client import BEFORE any backend patching: the client
        # module (and qwen_asr beneath it) reads torch backends at import
        # time, and the fake backends installed below would break that
        # first import. Construction alone loads no model.
        try:
            assert QwenLocalProvider is not None  # Type narrowing for PyLance
            QwenLocalProvider(SettingsType()).GetTranscriptionClient(SettingsType())
        except SubtitleError:
            self.skipTest("torch not installed")

    def _client(self, device_setting : str):
        assert QwenLocalProvider is not None  # Type narrowing for PyLance
        provider = QwenLocalProvider(SettingsType())
        return provider.GetTranscriptionClient(SettingsType({'device': device_setting}))

    def _no_accelerator(self):
        """Patch every GPU backend to unavailable for CPU-fallback cases."""
        return (
            patch("torch.cuda.is_available", return_value=False),
            patch("torch.backends.mps",
                  SimpleNamespace(is_available=lambda: False, is_built=lambda: False), create=True),
            patch("torch.xpu",
                  SimpleNamespace(is_available=lambda: False), create=True),
        )

    def test_auto_prefers_cuda(self):
        """Auto selection uses CUDA when present, with bfloat16 math."""
        with patch("torch.cuda.is_available", return_value=True):
            client = self._client('auto')

            self.assertLoggedEqual("auto device", "cuda:0", client.device)
            self.assertLoggedEqual("cuda dtype", "torch.bfloat16", str(client.inference_dtype))

    def test_auto_uses_mps_without_cuda(self):
        """Auto selection falls through to Apple Silicon with float16 math."""
        with patch("torch.cuda.is_available", return_value=False):
            with patch("torch.backends.mps",
                       SimpleNamespace(is_available=lambda: True, is_built=lambda: True),
                       create=True):
                client = self._client('auto')

                self.assertLoggedEqual("auto device", "mps", client.device)
                self.assertLoggedEqual("mps dtype", "torch.float16", str(client.inference_dtype))

    def test_auto_falls_back_to_cpu(self):
        """Auto selection lands on CPU with bfloat16 math when no accelerator exists."""
        cuda_off, mps_off, xpu_off = self._no_accelerator()
        with cuda_off, mps_off, xpu_off:
            client = self._client('auto')

            self.assertLoggedEqual("auto device", "cpu", client.device)
            self.assertLoggedEqual("cpu dtype", "torch.bfloat16", str(client.inference_dtype))

    def test_explicit_xpu_selected(self):
        """An explicit XPU request is honoured when the backend exists."""
        with patch("torch.xpu",
                   SimpleNamespace(is_available=lambda: True),
                   create=True):
            client = self._client('xpu')

            self.assertLoggedEqual("explicit device", "xpu:0", client.device)
            self.assertLoggedEqual("xpu dtype", "torch.float16", str(client.inference_dtype))

    def test_explicit_mps_selected(self):
        """An explicit MPS request is honoured when the backend exists."""
        with patch("torch.backends.mps",
                   SimpleNamespace(is_available=lambda: True, is_built=lambda: True),
                   create=True):
            client = self._client('mps')

            self.assertLoggedEqual("explicit device", "mps", client.device)

    def test_explicit_mps_unavailable_falls_back_to_cpu(self):
        """An explicit MPS request without the backend falls back to CPU."""
        with patch("torch.backends.mps",
                   SimpleNamespace(is_available=lambda: False, is_built=lambda: False),
                   create=True):
            client = self._client('mps')

            self.assertLoggedEqual("fallback device", "cpu", client.device)

    def test_explicit_cuda_unavailable_falls_back_to_cpu(self):
        """An explicit CUDA request without CUDA falls back to CPU."""
        with patch("torch.cuda.is_available", return_value=False):
            client = self._client('cuda')

            self.assertLoggedEqual("fallback device", "cpu", client.device)

    def test_invalid_device_falls_back_to_auto(self):
        """Unknown device names warn and resolve automatically."""
        with patch("torch.cuda.is_available", return_value=True):
            client = self._client('tpu')

            self.assertLoggedEqual("auto device", "cuda:0", client.device)

    def test_options_offer_accelerators(self):
        """The device dropdown lists every supported backend."""
        assert QwenLocalProvider is not None  # Type narrowing for PyLance
        provider = QwenLocalProvider(SettingsType())
        options = provider.GetOptions(provider.settings)
        devices, _tooltip = options['device']

        for name in ("auto", "cuda", "mps", "xpu", "cpu"):
            self.assertLoggedIn(f"{name} device", name, devices)

class TestQwenResultParsing(LoggedTestCase):
    def test_parse_timestamps(self):
        """qwen-asr results extract text, language and word timings."""
        unit = type("Unit", (), {'text': 'hello', 'start_time': 0.5, 'end_time': 0.9})()
        result = type("Result", (), {'text': 'hello', 'language': 'Chinese', 'time_stamps': [unit]})()
        text, language, words = parse_qwen_result(result)

        self.assertLoggedEqual("text", "hello", text)
        self.assertLoggedEqual("language", "Chinese", language)
        self.assertLoggedEqual("word count", 1, len(words))
        self.assertLoggedEqual("word start", timedelta(seconds=0.5), words[0].start)

    def test_parse_flat_result(self):
        """Results without timestamps parse to text-only."""
        result = type("Result", (), {'text': 'hi', 'language': None, 'time_stamps': None})()
        text, language, words = parse_qwen_result(result)

        self.assertLoggedEqual("text", "hi", text)
        self.assertLoggedEqual("language", None, language)
        self.assertLoggedEqual("word count", 0, len(words))

class TestQwenLanguage(LoggedTestCase):
    @skip_if_debugger_attached
    def test_provider_resolves_english_names(self):
        """Hints become the English names qwen-asr expects; unknown hints are rejected."""
        if QwenLocalProvider is None:
            self.skipTest("qwen-asr not installed")
        provider = QwenLocalProvider(SettingsType())

        self.assertLoggedIsNone("no hint", provider.ResolveLanguageCode(None))
        self.assertLoggedEqual("english name", "Chinese", provider.ResolveLanguageCode("chinese"))
        self.assertLoggedEqual("native name", "Chinese", provider.ResolveLanguageCode("\u4e2d\u6587"))
        self.assertLoggedEqual("regional code", "Chinese", provider.ResolveLanguageCode("zh-TW"))
        self.assertLoggedEqual("ui language name", "German", provider.ResolveLanguageCode("alem\u00e1n", "es"))

        with self.assertRaises(SubtitleError) as context:
            provider.ResolveLanguageCode("Klingon")
        self.log_expected_result(SubtitleError, type(context.exception), description="unknown hint rejected")

    def test_client_falls_back_to_auto_detect_outside_sdk_list(self):
        """A resolvable language the SDK cannot handle warns once at construction and auto-detects."""
        client_type = getattr(qwen_module, 'QwenLocalClient', None)
        if client_type is None:
            self.skipTest("qwen-asr not installed")

        client = client_type(SettingsType({'language': 'Chinese'}))
        self.assertLoggedEqual("supported language kept", "Chinese", client.language)

        client = client_type(SettingsType({'language': 'Welsh'}))
        self.assertLoggedIsNone("unsupported language dropped", client.language)

    def test_hint_passes_straight_to_model(self):
        """The client no longer normalises: the resolved name goes to the SDK unchanged."""
        client_type = getattr(qwen_module, 'QwenLocalClient', None)
        if client_type is None:
            self.skipTest("qwen-asr not installed")
        client = client_type(SettingsType({'language': 'Chinese'}))
        result = type("Result", (), {"text": "ni hao", "language": "Chinese", "time_stamps": None})()
        model = Mock()
        model.transcribe.return_value = [result]
        with patch.object(client, '_load_model', return_value=model), \
                patch.object(client, '_write_chunk', return_value="chunk.wav"), \
                patch.object(qwen_module.os, 'remove'):
            client._transcribe_chunk(b"audio", "wav")

        model.transcribe.assert_called_once_with(
            audio="chunk.wav", language="Chinese", return_time_stamps=True)


class TestQwenAlignment(LoggedTestCase):
    def test_auto_detect_requests_timestamps(self):
        """An omitted hint still enables Qwen forced alignment."""
        client_type = getattr(qwen_module, 'QwenLocalClient', None)
        if client_type is None:
            self.skipTest("qwen-asr not installed")
        client = client_type(SettingsType())
        result = type("Result", (), {"text": "hello", "language": "English", "time_stamps": None})()
        model = Mock()
        model.transcribe.return_value = [result]
        with patch.object(client, '_load_model', return_value=model), \
                patch.object(client, '_write_chunk', return_value="chunk.wav"), \
                patch.object(qwen_module.os, 'remove'):
            client._transcribe_chunk(b"audio", "wav")

        model.transcribe.assert_called_once_with(
            audio="chunk.wav", language=None, return_time_stamps=True)

    @skip_if_debugger_attached
    def test_unsupported_detected_language_falls_back_to_text(self):
        """Unsupported forced alignment tries English before text-only output."""
        client_type = getattr(qwen_module, 'QwenLocalClient', None)
        if client_type is None:
            self.skipTest("qwen-asr not installed")
        client = client_type(SettingsType())
        result = type("Result", (), {"text": "bonjour", "language": "Klingon", "time_stamps": None})()
        model = Mock()
        model.transcribe.side_effect = [
            ValueError("Unsupported language: Klingon"),
            ValueError("Unsupported language: English"),
            [result],
        ]
        with patch.object(client, '_load_model', return_value=model), \
                patch.object(client, '_write_chunk', return_value="chunk.wav"), \
                patch.object(qwen_module.os, 'remove'):
            transcription = client._transcribe_chunk(b"audio", "wav")

        self.assertLoggedEqual("fallback text", "bonjour", transcription.text)
        self.assertLoggedEqual("retry count", 3, model.transcribe.call_count)
        self.assertLoggedEqual("alignment retry language", "English",
                               model.transcribe.call_args_list[1].kwargs['language'])
        self.assertLoggedEqual("alignment retry timestamps", True,
                               model.transcribe.call_args_list[1].kwargs['return_time_stamps'])
        self.assertLoggedEqual("fallback timestamps", False,
                               model.transcribe.call_args_list[2].kwargs['return_time_stamps'])


class TestQwenModelCache(LoggedTestCase):
    def setUp(self):
        super().setUp()
        client_type = getattr(qwen_module, 'QwenLocalClient', None)
        if client_type is None:
            self.skipTest("qwen-asr not installed")
        self.client_type : type[Any] = client_type

        self._saved_key = qwen_module._loaded_key
        self._saved_model = qwen_module._loaded_model
        qwen_module._loaded_key = None
        qwen_module._loaded_model = None

    def tearDown(self):
        qwen_module._loaded_key = self._saved_key
        qwen_module._loaded_model = self._saved_model
        super().tearDown()

    def test_generation_budget_applied_per_call(self):
        """A changed max_new_tokens setting applies to a reused model."""
        client = self.client_type(SettingsType({'max_new_tokens': 2048}))
        result = type("Result", (), {"text": "hello", "language": "English", "time_stamps": None})()
        model = Mock()
        model.transcribe.return_value = [result]
        with patch.object(client, '_load_model', return_value=model), \
                patch.object(client, '_write_chunk', return_value="chunk.wav"), \
                patch.object(qwen_module.os, 'remove'):
            client._transcribe_chunk(b"audio", "wav")

        self.assertLoggedEqual("budget set on model", 2048, model.max_new_tokens)

    def test_settings_change_replaces_cached_model(self):
        """Only the most recently loaded model is retained; the previous one is released."""
        loaded : list[Mock] = []

        def fake_load(checkpoint, **kwargs):
            model = Mock(name=checkpoint)
            loaded.append(model)
            return model

        with patch.object(qwen_module.Qwen3ASRModel, 'from_pretrained', side_effect=fake_load) as from_pretrained, \
                patch.object(qwen_module.torch.cuda, 'is_available', return_value=False), \
                patch.object(qwen_module, '_mps_available', return_value=False):
            first = self.client_type(SettingsType({'model': 'Qwen/Qwen3-ASR-1.7B', 'device': 'cpu'}))
            first_model = first._load_model()
            self.assertLoggedIs("first load cached", first_model, qwen_module._loaded_model)

            same = self.client_type(SettingsType({'model': 'Qwen/Qwen3-ASR-1.7B', 'device': 'cpu', 'max_new_tokens': 4096}))
            self.assertLoggedIs("budget change reuses model", first_model, same._load_model())
            self.assertLoggedEqual("single load so far", 1, from_pretrained.call_count)

            second = self.client_type(SettingsType({'model': 'Qwen/Qwen3-ASR-0.6B', 'device': 'cpu'}))
            second_model = second._load_model()
            self.assertLoggedEqual("second load performed", 2, from_pretrained.call_count)
            self.assertLoggedIs("latest model cached", second_model, qwen_module._loaded_model)
            self.assertLoggedIsNot("previous model dropped", first_model, qwen_module._loaded_model)

            again = self.client_type(SettingsType({'model': 'Qwen/Qwen3-ASR-1.7B', 'device': 'cpu'}))
            again._load_model()
            self.assertLoggedEqual("original key reloads", 3, from_pretrained.call_count)


if __name__ == '__main__':
    unittest.main()
