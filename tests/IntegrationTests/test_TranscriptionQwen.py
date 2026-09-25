import importlib.util
import sys
import tempfile
import unittest
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import skip_if_debugger_attached
from PySubtrans.SettingsType import SettingsType
from PySubtrans.Transcription.TranscriptionProvider import OptionsScope
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionCoordinator import TranscriptionCoordinator
from PySubtrans.Transcription.TranscriptionOutcome import TranscriptionStatus
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from PySubtrans.Transcription.Providers.Provider_QwenLocal import QwenLocalProvider
from PySubtrans.Transcription.Providers.Clients import QwenLocalClient as qwen_module

QWEN_ASR_AVAILABLE = importlib.util.find_spec("qwen_asr") is not None
QwenLocalClientClass = qwen_module.QwenLocalClient

class TestQwenLocalProvider(LoggedTestCase):
    def setUp(self):
        super().setUp()

    def test_registered(self):
        """Qwen Local registers when its SDK is present."""
        providers = TranscriptionProvider.get_providers()

        self.assertLoggedIn("qwen present", "Qwen Local", providers)

    def test_options_ungated_when_torch_configured(self):
        """Full schema is shown when torch_installation_directory is set."""
        provider = QwenLocalProvider(SettingsType({'torch_installation_directory': '/fake/path'}))
        options = provider.GetOptions(provider.settings)

        for key in ("model", "language", "device", "aligner_model", "max_new_tokens", "rate_limit",
                    "allow_cpu_fallback", "torch_installation_directory"):
            self.assertLoggedIn(f"{key} option", key, options)
        self.assertLoggedIn("checkpoint", "Qwen/Qwen3-ASR-1.7B", provider.GetAvailableModels())

        self.assertLoggedEqual("CPU fallback default", False, provider.settings.get_bool('allow_cpu_fallback'))
        per_run = provider.GetOptions(provider.settings, OptionsScope.PER_RUN)
        self.assertLoggedNotIn("CPU fallback is not a per-run choice", "allow_cpu_fallback", per_run)
        self.assertLoggedNotIn("Torch directory is not a per-run choice", "torch_installation_directory", per_run)

    def test_options_progressive_disclosure_when_unconfigured(self):
        """Only the torch setup option is shown when torch is not configured."""
        provider = QwenLocalProvider(SettingsType())
        options = provider.GetOptions(provider.settings)

        self.assertLoggedIn("torch_installation_directory shown", "torch_installation_directory", options)
        self.assertLoggedEqual("only one option", 1, len(options))

    def test_provider_information_has_no_none_literal(self):
        """Provider information contains no interpolation artefacts."""
        provider = QwenLocalProvider(SettingsType())
        info = provider.GetInformation(torch_device='cuda:0')

        self.assertLoggedIsNotNone("provider information", info)
        if info:
            self.assertNotIn('None', info)

    def test_provider_information_explains_torch_setup_when_unconfigured(self):
        """Unconfigured Qwen Local explains how to install and select Torch."""
        provider = QwenLocalProvider(SettingsType())
        info = provider.GetInformation(ffmpeg_available=True)

        self.assertLoggedIsNotNone("provider information", info)
        if info:
            self.assertLoggedIn(f"Torch setup guidance", "Torch setup required", info)

    def test_provider_information_hides_setup_guidance_when_configured(self):
        """Configured Qwen Local does not repeat the initial setup walkthrough."""
        provider = QwenLocalProvider(SettingsType({'torch_installation_directory': '/fake/path'}))
        info = provider.GetInformation(ffmpeg_available=True, torch_device='cuda:0')

        self.assertLoggedIsNotNone("provider information", info)
        if info:
            self.assertLoggedNotIn("setup guidance omitted", "Torch setup required", info)

    def test_cpu_fallback_setting_refreshes_provider_information(self):
        """The settings dialog refreshes the disclaimer when consent changes."""
        provider = QwenLocalProvider(SettingsType())

        self.assertLoggedIn('CPU fallback refresh trigger', 'allow_cpu_fallback', provider.refresh_when_changed)

    def test_validate_requires_torch_directory_in_frozen_build(self):
        """Frozen builds reject Qwen when no external Torch directory is configured."""
        provider = QwenLocalProvider(SettingsType())
        with patch.object(sys, 'frozen', True, create=True):
            self.assertLoggedEqual("frozen build without Torch", False, provider.ValidateSettings())

    def test_validate_passes_with_torch_directory(self):
        """ValidateSettings returns True when torch_installation_directory is set."""
        provider = QwenLocalProvider(SettingsType({'torch_installation_directory': '/fake/path'}))
        self.assertLoggedEqual("valid with torch", True, provider.ValidateSettings())

    @patch('PySubtrans.Transcription.AudioExtractor.CheckFfmpegAvailable')
    @patch.object(qwen_module, "_load_qwen_dependencies", side_effect=ImportError("missing torch"))
    def test_missing_torch_returns_coordinator_compatible_error(self, _load_dependencies, _check_ffmpeg):
        """A missing Torch runtime becomes a failed outcome instead of leaking ImportError."""
        provider = QwenLocalProvider(SettingsType())
        coordinator = TranscriptionCoordinator(provider, SettingsType())

        with tempfile.NamedTemporaryFile(suffix=".wav") as media:
            outcome = coordinator.TranscribeMedia(media.name)

        self.assertLoggedEqual("missing Torch status", TranscriptionStatus.FAILED, outcome.status)
        self.assertLoggedIsInstance("missing Torch error", outcome.error, SubtitleError)
        assert outcome.error is not None
        self.assertLoggedIn("actionable Torch message", "external Torch", outcome.error.message or "")
        self.assertLoggedIsInstance("original loader cause", outcome.error.error, ImportError)


@unittest.skipUnless(QWEN_ASR_AVAILABLE, "qwen-asr not installed")
class TestQwenLocalDevice(LoggedTestCase):
    def setUp(self):
        super().setUp()
        # Warm the lazy client import BEFORE any backend patching: the client
        # module (and qwen_asr beneath it) reads torch backends at import
        # time, and the fake backends installed below would break that
        # first import. Construction alone loads no model.
        try:
            QwenLocalProvider(SettingsType()).GetTranscriptionClient(SettingsType())
        except SubtitleError:
            self.skipTest("torch not installed")

    def _client(self, device_setting : str, allow_cpu_fallback : bool = False) -> qwen_module.QwenLocalClient:
        provider = QwenLocalProvider(SettingsType())
        client = provider.GetTranscriptionClient(SettingsType({
            'device': device_setting,
            'allow_cpu_fallback': allow_cpu_fallback,
        }))
        assert isinstance(client, QwenLocalClientClass)
        return client

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

    def test_auto_refuses_cpu_without_fallback_consent(self):
        """Auto selection refuses CPU when no accelerator exists without consent."""
        cuda_off, mps_off, xpu_off = self._no_accelerator()
        with cuda_off, mps_off, xpu_off:
            client = self._client('auto')

            with self.assertRaises(SubtitleError) as context:
                _device = client.device
            self.assertIn('allow_cpu_fallback', str(context.exception))

    def test_auto_uses_cpu_when_fallback_is_enabled(self):
        """Auto selection uses CPU only after explicit consent."""
        cuda_off, mps_off, xpu_off = self._no_accelerator()
        with cuda_off, mps_off, xpu_off:
            client = self._client('auto', allow_cpu_fallback=True)

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

    def test_explicit_mps_unavailable_is_refused_without_fallback_consent(self):
        """An unavailable explicit MPS request fails without CPU consent."""
        with patch("torch.backends.mps",
                   SimpleNamespace(is_available=lambda: False, is_built=lambda: False),
                   create=True):
            client = self._client('mps')

            with self.assertRaises(SubtitleError) as context:
                _device = client.device
            self.assertIn('unavailable', str(context.exception))

    def test_explicit_cuda_unavailable_uses_cpu_with_fallback_consent(self):
        """An unavailable explicit CUDA request uses CPU after consent."""
        with patch("torch.cuda.is_available", return_value=False):
            client = self._client('cuda', allow_cpu_fallback=True)

            self.assertLoggedEqual("fallback device", "cpu", client.device)

    def test_explicit_cpu_is_refused_without_fallback_consent(self):
        """Explicit CPU selection requires the persistent consent setting."""
        client = self._client('cpu')

        with self.assertRaises(SubtitleError) as context:
            _device = client.device
        self.assertIn('allow_cpu_fallback', str(context.exception))

    def test_explicit_cpu_is_allowed_with_fallback_consent(self):
        """Explicit CPU selection is allowed after consent."""
        client = self._client('cpu', allow_cpu_fallback=True)

        self.assertLoggedEqual("explicit CPU device", "cpu", client.device)

    def test_invalid_device_falls_back_to_auto(self):
        """Unknown device names warn and resolve automatically."""
        with patch("torch.cuda.is_available", return_value=True):
            client = self._client('tpu')

            self.assertLoggedEqual("auto device", "cuda:0", client.device)

    def test_options_offer_accelerators(self):
        """The device dropdown lists every supported backend."""
        provider = QwenLocalProvider(SettingsType({'torch_installation_directory': '/fake/path'}))
        options = provider.GetOptions(provider.settings)
        devices, _tooltip = options['device']

        for name in ("auto", "cuda", "mps", "xpu", "cpu"):
            self.assertLoggedIn(f"{name} device", name, devices)

class TestQwenResultParsing(LoggedTestCase):
    def test_parse_timestamps(self):
        """qwen-asr results extract text, language and word timings."""
        unit = type("Unit", (), {'text': 'hello', 'start_time': 0.5, 'end_time': 0.9})()
        result = type("Result", (), {'text': 'hello', 'language': 'Chinese', 'time_stamps': [unit]})()
        text, language, words = qwen_module.parse_qwen_result(result)

        self.assertLoggedEqual("text", "hello", text)
        self.assertLoggedEqual("language", "Chinese", language)
        self.assertLoggedEqual("word count", 1, len(words))
        self.assertLoggedEqual("word start", timedelta(seconds=0.5), words[0].start)

    def test_parse_flat_result(self):
        """Results without timestamps parse to text-only."""
        result = type("Result", (), {'text': 'hi', 'language': None, 'time_stamps': None})()
        text, language, words = qwen_module.parse_qwen_result(result)

        self.assertLoggedEqual("text", "hi", text)
        self.assertLoggedEqual("language", None, language)
        self.assertLoggedEqual("word count", 0, len(words))

class TestQwenLanguage(LoggedTestCase):
    @skip_if_debugger_attached
    def test_provider_resolves_english_names(self):
        """Hints become the English names qwen-asr expects; unknown hints are rejected."""
        provider = QwenLocalProvider(SettingsType())

        self.assertLoggedIsNone("no hint", provider.ResolveLanguageCode(None))
        self.assertLoggedEqual("english name", "Chinese", provider.ResolveLanguageCode("chinese"))
        self.assertLoggedEqual("native name", "Chinese", provider.ResolveLanguageCode("\u4e2d\u6587"))
        self.assertLoggedEqual("regional code", "Chinese", provider.ResolveLanguageCode("zh-TW"))
        self.assertLoggedEqual("ui language name", "German", provider.ResolveLanguageCode("alem\u00e1n", "es"))

        with self.assertRaises(SubtitleError) as context:
            provider.ResolveLanguageCode("Klingon")
        self.log_expected_result(SubtitleError, type(context.exception), description="unknown hint rejected")

    @unittest.skipUnless(QWEN_ASR_AVAILABLE, "qwen-asr not installed")
    def test_client_falls_back_to_auto_detect_outside_sdk_list(self):
        """A resolvable language the SDK cannot handle warns once at construction and auto-detects."""
        client_type = QwenLocalClientClass

        client = client_type(SettingsType({'language': 'Chinese'}))
        self.assertLoggedEqual("supported language kept", "Chinese", client.language)

        client = client_type(SettingsType({'language': 'Welsh'}))
        self.assertLoggedIsNone("unsupported language dropped", client.language)

    @unittest.skipUnless(QWEN_ASR_AVAILABLE, "qwen-asr not installed")
    def test_hint_passes_straight_to_model(self):
        """The client no longer normalises: the resolved name goes to the SDK unchanged."""
        client_type = QwenLocalClientClass
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


@unittest.skipUnless(QWEN_ASR_AVAILABLE, "qwen-asr not installed")
class TestQwenAlignment(LoggedTestCase):
    def test_auto_detect_requests_timestamps(self):
        """An omitted hint still enables Qwen forced alignment."""
        client_type = QwenLocalClientClass
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
        client_type = QwenLocalClientClass
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


@unittest.skipUnless(QWEN_ASR_AVAILABLE, "qwen-asr not installed")
class TestQwenModelCache(LoggedTestCase):
    def setUp(self):
        super().setUp()
        self.client_type : type[Any] = QwenLocalClientClass

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

        assert qwen_module.torch is not None  # torch loaded by module-level setup
        _torch_cuda = qwen_module.torch.cuda
        with patch.object(qwen_module.Qwen3ASRModel, 'from_pretrained', side_effect=fake_load) as from_pretrained, \
                patch.object(_torch_cuda, 'is_available', return_value=False), \
                patch.object(qwen_module, '_mps_available', return_value=False):
            first = self.client_type(SettingsType({'model': 'Qwen/Qwen3-ASR-1.7B', 'device': 'cpu', 'allow_cpu_fallback': True}))
            first_model = first._load_model()
            self.assertLoggedIs("first load cached", first_model, qwen_module._loaded_model)

            same = self.client_type(SettingsType({'model': 'Qwen/Qwen3-ASR-1.7B', 'device': 'cpu', 'allow_cpu_fallback': True, 'max_new_tokens': 4096}))
            self.assertLoggedIs("budget change reuses model", first_model, same._load_model())
            self.assertLoggedEqual("single load so far", 1, from_pretrained.call_count)

            second = self.client_type(SettingsType({'model': 'Qwen/Qwen3-ASR-0.6B', 'device': 'cpu', 'allow_cpu_fallback': True}))
            second_model = second._load_model()
            self.assertLoggedEqual("second load performed", 2, from_pretrained.call_count)
            self.assertLoggedIs("latest model cached", second_model, qwen_module._loaded_model)
            self.assertLoggedIsNot("previous model dropped", first_model, qwen_module._loaded_model)

            again = self.client_type(SettingsType({'model': 'Qwen/Qwen3-ASR-1.7B', 'device': 'cpu', 'allow_cpu_fallback': True}))
            again._load_model()
            self.assertLoggedEqual("original key reloads", 3, from_pretrained.call_count)


if __name__ == '__main__':
    unittest.main()
