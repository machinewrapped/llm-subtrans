"""Qwen provider integration and an opt-in real worker smoke test.

Set QWEN_TEST_ENVIRONMENT to a Torch/Qwen venv and QWEN_TEST_AUDIO to speech media.
QWEN_TEST_START_SECONDS optionally selects the beginning of the 20-second excerpt.
"""

import io
import json
import os
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import skip_if_debugger_attached
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.AudioExtractor import AudioExtractor
from PySubtrans.Transcription.Providers.Clients import QwenLocalClient as client_module
from PySubtrans.Transcription.Providers.Clients.QwenLocalClient import QwenLocalClient
from PySubtrans.Transcription.Providers.Provider_QwenLocal import QwenLocalProvider
from PySubtrans.Transcription.Torch.QwenRuntime import HasQwenRuntime
from PySubtrans.Transcription.Torch.LocalRuntime import TorchConfigOption
from PySubtrans.Transcription.TranscriptionProvider import OptionsScope, TranscriptionProvider
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult
from PySubtrans.Transcription.WorkerHost import WorkerError
from PySubtrans.Transcription.Workers import qwen_worker

NEEDS_QWEN_RUNTIME = 'PySubtrans.Transcription.Providers.Provider_QwenLocal.NeedsQwenRuntime'
QWEN_TEST_ENVIRONMENT = os.getenv('QWEN_TEST_ENVIRONMENT', '')
QWEN_TEST_AUDIO = os.getenv('QWEN_TEST_AUDIO', '')

class TestQwenLocalProvider(LoggedTestCase):
    def test_registered(self) -> None:
        """Qwen Local registers without importing its SDK."""
        providers = TranscriptionProvider.get_providers()

        self.assertLoggedIn("qwen present", "Qwen Local", providers)

    def test_options_ungated_when_torch_configured(self) -> None:
        """Full schema is shown when qwen_installation_directory is set."""
        provider = QwenLocalProvider(SettingsType({'qwen_installation_directory': '/fake/path'}))
        with patch(NEEDS_QWEN_RUNTIME, return_value=False):
            options = provider.GetOptions(provider.settings)
            per_run = provider.GetOptions(provider.settings, OptionsScope.PER_RUN)

        for key in ("model", "language", "device", "aligner_model", "max_new_tokens", "rate_limit",
                    "allow_cpu_fallback", "qwen_installation_directory"):
            self.assertLoggedIn(f"{key} option", key, options)
        self.assertLoggedIn("checkpoint", "Qwen/Qwen3-ASR-1.7B", provider.GetAvailableModels())

        self.assertLoggedEqual("CPU fallback default", False, provider.settings.get_bool('allow_cpu_fallback'))
        self.assertLoggedNotIn("CPU fallback is not a per-run choice", "allow_cpu_fallback", per_run)
        self.assertLoggedNotIn("Torch directory is not a per-run choice", "qwen_installation_directory", per_run)

    def test_options_progressive_disclosure_when_unconfigured(self) -> None:
        """Only the torch setup option is shown when torch is not configured."""
        provider = QwenLocalProvider(SettingsType())
        options = provider.GetOptions(provider.settings)

        self.assertLoggedIn("qwen_installation_directory shown", "qwen_installation_directory", options)
        self.assertLoggedEqual("only one option", 1, len(options))

    def test_provider_information_has_no_none_literal(self) -> None:
        """Provider information contains no interpolation artefacts."""
        provider = QwenLocalProvider(SettingsType())
        info = provider.GetInformation(torch_device='cuda:0')

        self.assertLoggedIsNotNone("provider information", info)
        if info:
            self.assertNotIn('None', info)

    def test_provider_information_explains_torch_setup_when_unconfigured(self) -> None:
        """Unconfigured Qwen Local explains how to install and select Torch."""
        provider = QwenLocalProvider(SettingsType())
        info = provider.GetInformation(ffmpeg_available=True)

        self.assertLoggedIsNotNone("provider information", info)
        if info:
            self.assertLoggedIn("setup action named", TorchConfigOption.label, info)

    def test_provider_information_hides_setup_guidance_when_configured(self) -> None:
        """Configured Qwen Local does not repeat the initial setup walkthrough."""
        provider = QwenLocalProvider(SettingsType({'qwen_installation_directory': '/fake/path'}))
        with patch(NEEDS_QWEN_RUNTIME, return_value=False):
            info = provider.GetInformation(ffmpeg_available=True, torch_device='cuda:0')

        self.assertLoggedIsNotNone("provider information", info)
        if info:
            self.assertLoggedNotIn("setup action omitted", TorchConfigOption.label, info)

    def test_cpu_fallback_setting_refreshes_provider_information(self) -> None:
        """The settings dialog refreshes the disclaimer when consent changes."""
        provider = QwenLocalProvider(SettingsType())

        self.assertLoggedIn('CPU fallback refresh trigger', 'allow_cpu_fallback', provider.refresh_when_changed)

    def test_validate_requires_torch_directory_in_frozen_build(self) -> None:
        """Frozen builds reject Qwen when no external Torch directory is configured."""
        provider = QwenLocalProvider(SettingsType())
        with patch.object(sys, 'frozen', True, create=True):
            self.assertLoggedEqual("frozen build without Torch", False, provider.ValidateSettings())

    def test_validate_passes_with_torch_directory(self) -> None:
        """ValidateSettings returns True when qwen_installation_directory is set."""
        provider = QwenLocalProvider(SettingsType({'qwen_installation_directory': '/fake/path'}))
        with patch(NEEDS_QWEN_RUNTIME, return_value=False):
            self.assertLoggedEqual("valid with torch", True, provider.ValidateSettings())

    def test_frozen_build_gates_torch_environment_without_qwen_runtime(self) -> None:
        """A Torch environment set up for 1.7.0 lacks the Qwen runtime, so only the setup option is offered."""
        provider = QwenLocalProvider(SettingsType({'qwen_installation_directory': '/torch-env'}))

        with patch(NEEDS_QWEN_RUNTIME, return_value=True), patch.object(sys, 'frozen', True, create=True):
            options = provider.GetOptions(provider.settings)
            valid = provider.ValidateSettings()

        self.assertLoggedEqual("only the setup option", ['qwen_installation_directory'], list(options))
        self.assertLoggedEqual("settings invalid without the Qwen runtime", False, valid)

    def test_frozen_build_accepts_torch_environment_with_qwen_runtime(self) -> None:
        """A Torch environment with the Qwen runtime is ready for transcription."""
        provider = QwenLocalProvider(SettingsType({'qwen_installation_directory': '/torch-env'}))

        with patch(NEEDS_QWEN_RUNTIME, return_value=False), patch.object(sys, 'frozen', True, create=True):
            options = provider.GetOptions(provider.settings)
            valid = provider.ValidateSettings()

        self.assertLoggedIn("model option offered", 'model', options)
        self.assertLoggedEqual("settings valid", True, valid)


class TestQwenLanguage(LoggedTestCase):
    @skip_if_debugger_attached
    def test_provider_resolves_english_names(self) -> None:
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

class TestQwenWorkerMapping(LoggedTestCase):
    """The SDK-free client owns transcript normalization and WordTiming creation."""

    def test_result_mapping(self) -> None:
        """Keep valid stamps in emission order, clamp negatives and keep zero lengths."""
        response = {
            'text': ' hello world ', 'language': ' English ',
            'time_stamps': [dict(text=text, start_time=start, end_time=end) for text, start, end in (
                (' world ', 1.2, 1.5), (' hello ', -0.1, 0.0), ('zero', 1.3, 1.3),
                ('bad', 2.0, 1.0), ('missing', None, 3.0), (' ', 0, 1))],
        }
        result = client_module.QwenLocalClient.ParseResult(response)
        self.assertLoggedIsInstance('application result', result, TranscriptionResult)
        self.assertLoggedEqual('transcript normalized', 'hello world', result.text)
        self.assertLoggedEqual('language normalized', 'English', result.language)
        self.assertLoggedEqual('stamp order preserved', ['world', 'hello', 'zero'], [word.text for word in result.words])
        self.assertLoggedEqual('negative start clamped', timedelta(), result.words[1].start)
        self.assertLoggedEqual('zero duration kept', result.words[2].start, result.words[2].end)
        self.assertLoggedEqual('no invented parts', [], result.parts)

    def test_empty_and_text_only_results(self) -> None:
        """Silence and unsupported alignment retain the hint when detection is absent."""
        for text in ('', 'flat transcript'):
            result = client_module.QwenLocalClient.ParseResult({'text': text, 'language': None, 'time_stamps': []}, 'Chinese')
            self.assertLoggedEqual('transcript', text, result.text)
            self.assertLoggedEqual('hint fallback', 'Chinese', result.language)
            self.assertLoggedEqual('no words', [], result.words)

    @skip_if_debugger_attached
    def test_bad_payloads(self) -> None:
        """Invalid worker result shapes fail at the application boundary."""
        for response in ({}, {'text': 4, 'time_stamps': []}, {'text': '', 'time_stamps': None},
                         {'text': '', 'time_stamps': [], 'language': 5}, {'text': '', 'time_stamps': [None]}):
            with self.assertRaises(WorkerError):
                client_module.QwenLocalClient.ParseResult(response)


class TestQwenWorkerSession(LoggedTestCase):
    """Model cache and abort use fake hosts and never write temporary chunks."""

    def setUp(self) -> None:
        super().setUp()
        self.state = patch.multiple(client_module, _loaded_worker=None, _loaded_key=None, _loaded_ready={})
        self.state.start()
        self.addCleanup(self.state.stop)
        self.resolve = patch.object(client_module, 'ResolveEnvironmentPython', return_value='python')
        self.resolve.start()
        self.addCleanup(self.resolve.stop)
        self.hosts : list[Mock] = []

        def Host(*args : Any) -> Mock:
            host = Mock()
            host.running = True
            host.Request.return_value = {'type': 'ready', 'device': 'cuda:0', 'supported_languages': ['English', 'Chinese']}
            self.hosts.append(host)
            return host

        self.factory = patch.object(client_module, 'WorkerHost', side_effect=Host)
        self.factory.start()
        self.addCleanup(self.factory.stop)

    def test_cache_and_eviction(self) -> None:
        """Budget changes reuse a worker; load and environment changes evict it."""
        first = client_module.QwenLocalClient(SettingsType())
        worker = first._LoadWorker()
        again = client_module.QwenLocalClient(SettingsType({'max_new_tokens': 4096}))
        self.assertLoggedIs('budget change reuses model', worker, again._LoadWorker())
        for setting in ({'model': 'different'}, {'aligner_model': 'other'}, {'device': 'cpu'}, {'allow_cpu_fallback': True}):
            previous = self.hosts[-1]
            client_module.QwenLocalClient(SettingsType(setting))._LoadWorker()
            self.assertLoggedEqual('old worker shut down', 1, previous.Shutdown.call_count)
        with patch.object(client_module, 'ResolveEnvironmentPython', return_value='different-python'):
            client_module.QwenLocalClient(SettingsType())._LoadWorker()
        self.assertLoggedEqual('replacement per load change', 6, len(self.hosts))

    def test_generation_and_chunk_cleanup(self) -> None:
        """Each call sends its current budget, hint and alignment setting, then removes the WAV."""
        client = client_module.QwenLocalClient(SettingsType({'language': 'Chinese', 'max_new_tokens': 4096}))
        client._LoadWorker()
        worker = self.hosts[-1]
        worker.Request.return_value = {'type': 'result', 'text': 'hello', 'language': None, 'time_stamps': []}
        with patch.object(client, '_WriteChunk', return_value='chunk.wav'), patch.object(client_module.os, 'remove') as remove:
            result = client.TranscribeChunk(b'audio', 'wav')
        request = worker.Request.call_args.args[0]
        self.assertLoggedEqual('generation budget', 4096, request['max_new_tokens'])
        self.assertLoggedEqual('hint passed to worker', 'Chinese', request['language'])
        self.assertLoggedEqual('align by default', True, request['align'])
        self.assertLoggedEqual('hint retained in result', 'Chinese', result.language)
        self.assertLoggedEqual('WAV removed', 1, remove.call_count)

    @skip_if_debugger_attached
    def test_failed_request_cleans_chunk(self) -> None:
        """Temporary audio is removed after a runtime failure too."""
        client = client_module.QwenLocalClient(SettingsType())
        client._LoadWorker()
        worker = self.hosts[-1]
        worker.Request.side_effect = WorkerError('failure')
        with patch.object(client, '_WriteChunk', return_value='chunk.wav'), patch.object(client_module.os, 'remove') as remove:
            with self.assertRaises(WorkerError):
                client.TranscribeChunk(b'audio', 'wav')
        self.assertLoggedEqual('failed WAV removed', 1, remove.call_count)

    def test_unsupported_hint(self) -> None:
        """Language-list validation stays on the application side."""
        client = client_module.QwenLocalClient(SettingsType({'language': 'Welsh'}))
        with self.assertLogs(level='WARNING'):
            client._LoadWorker()
        self.assertLoggedIsNone('auto detect unsupported hint', client.language)

    def test_abort(self) -> None:
        """An active client abort terminates its worker."""
        client = client_module.QwenLocalClient(SettingsType())
        client._LoadWorker()
        host = self.hosts[-1]
        client.AbortTranscription()
        self.assertLoggedTrue('client aborted', client.aborted)
        self.assertLoggedEqual('host terminated', 1, host.Abort.call_count)

    @skip_if_debugger_attached
    def test_abort_before_loading(self) -> None:
        """A cancelled client cannot start a new worker."""
        client = client_module.QwenLocalClient(SettingsType())
        client.AbortTranscription()
        with self.assertRaises(SubtitleError):
            client._LoadWorker()
        self.assertLoggedEqual('no process created', 0, len(self.hosts))


class TestQwenWorkerRuntime(LoggedTestCase):
    """Qwen SDK and Torch backends are represented by in-memory objects."""

    def setUp(self) -> None:
        super().setUp()
        self.worker = qwen_worker.QwenWorker()
        self.model = Mock()
        self.worker.model = self.model

    @skip_if_debugger_attached
    def test_alignment_fallback(self) -> None:
        """An unsupported detected language retries English, then text only."""
        self.model.transcribe.side_effect = [ValueError('Unsupported language: Welsh'), ValueError('alignment'),
                                            [SimpleNamespace(text='text', language='Welsh', time_stamps=None)]]
        with self.assertLogs(level='WARNING') as logs:
            response = self.worker.Transcribe({'path': 'chunk.wav', 'language': None, 'max_new_tokens': 2048})
        calls = self.model.transcribe.call_args_list
        self.assertLoggedEqual('fallback attempts', 3, len(calls))
        self.assertLoggedEqual('English retry', 'English', calls[1].kwargs['language'])
        self.assertLoggedFalse('last call text only', calls[2].kwargs['return_time_stamps'])
        self.assertLoggedEqual('empty stamps returned', [], response['time_stamps'])
        self.assertLoggedEqual('warnings captured', 2, len(logs.records))

    @skip_if_debugger_attached
    def test_unrelated_error_is_not_retried(self) -> None:
        """Only unsupported aligner languages trigger retry."""
        self.model.transcribe.side_effect = ValueError('invalid audio')
        with self.assertRaises(ValueError):
            self.worker.Transcribe({'path': 'chunk.wav', 'max_new_tokens': 1024})
        self.assertLoggedEqual('single attempt', 1, self.model.transcribe.call_count)

    def test_raw_stamps_and_generation_budget(self) -> None:
        """The worker serializes raw fields without normalizing or reordering."""
        unit = SimpleNamespace(text=' raw ', start_time=-0.1, end_time=0.4)
        self.model.transcribe.return_value = [SimpleNamespace(text=' text ', language='English', time_stamps=[unit])]
        response = self.worker.Transcribe({'path': 'chunk.wav', 'max_new_tokens': 4096, 'align': False})
        self.assertLoggedEqual('budget applied', 4096, self.model.max_new_tokens)
        self.assertLoggedEqual('raw transcript', ' text ', response['text'])
        self.assertLoggedEqual('raw negative stamp', -0.1, response['time_stamps'][0]['start_time'])
        self.assertLoggedFalse('alignment disabled', self.model.transcribe.call_args.kwargs['return_time_stamps'])

    def test_silence(self) -> None:
        """No SDK results is expected for silence."""
        self.model.transcribe.return_value = []
        response = self.worker.Transcribe({'path': 'chunk.wav', 'max_new_tokens': 1024})
        self.assertLoggedEqual('empty transcription', '', response['text'])
        self.assertLoggedEqual('empty stamps', [], response['time_stamps'])

    @skip_if_debugger_attached
    def test_protocol_service(self) -> None:
        """Malformed requests and runtime failures return errors without corrupting the channel."""
        requests = io.StringIO('not JSON\n[]\n{"type":"unknown"}\n{"type":"load"}\n'
                               '{"type":"transcribe"}\n{"type":"shutdown"}\n')
        channel = io.StringIO()
        fake = Mock()
        fake.model = None
        fake.Load.return_value = {'type': 'ready', 'device': 'cpu', 'supported_languages': ['English']}
        fake.Transcribe.side_effect = ValueError('SDK failure')
        with patch.object(qwen_worker.sys, 'stdin', requests), patch.object(qwen_worker, '_channel', channel), \
                patch.object(qwen_worker, 'QwenWorker', return_value=fake):
            qwen_worker.Main()
        responses = [json.loads(line) for line in channel.getvalue().splitlines()]
        self.assertLoggedEqual('one reply per request except shutdown', 5, len(responses))
        self.assertLoggedEqual('protocol sequence', ['error', 'error', 'error', 'ready', 'error'],
                               [response['type'] for response in responses])
        self.assertLoggedEqual('runtime exception classification', 'ValueError', responses[-1]['error_type'])

    def test_load_model_and_aligner(self) -> None:
        """Both models keep the original device, dtype and generation settings."""
        for configured, expected_device, expected_dtype in (('cuda', 'cuda:0', 'bf16'), ('mps', 'mps', 'fp16'),
                                                            ('xpu', 'xpu:0', 'fp16'), ('cpu', 'cpu', 'bf16')):
            torch = SimpleNamespace(
                cuda=SimpleNamespace(is_available=lambda: True), bfloat16='bf16', float16='fp16',
                backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True, is_built=lambda: True)),
                xpu=SimpleNamespace(is_available=lambda: True))
            factory = Mock(return_value=self.model)
            modules = {'torch': torch, 'qwen_asr': SimpleNamespace(Qwen3ASRModel=SimpleNamespace(from_pretrained=factory)),
                       'qwen_asr.inference.utils': SimpleNamespace(SUPPORTED_LANGUAGES=['English'])}
            with patch.object(qwen_worker.importlib, 'import_module', side_effect=modules.__getitem__), \
                    patch.object(self.worker, 'InstallKoreanTokenizerFallback'):
                ready = self.worker.Load({'checkpoint': 'asr', 'aligner_checkpoint': 'aligner', 'device': configured,
                                          'max_new_tokens': 2048, 'allow_cpu_fallback': True})
            kwargs = factory.call_args.kwargs
            self.assertLoggedEqual('device selected', expected_device, ready['device'])
            self.assertLoggedEqual('model dtype', expected_dtype, kwargs['dtype'])
            self.assertLoggedEqual('aligner dtype and device', {'dtype': expected_dtype, 'device_map': expected_device},
                                   kwargs['forced_aligner_kwargs'])
            self.assertLoggedEqual('forced aligner loaded', 'aligner', kwargs['forced_aligner'])
            self.assertLoggedEqual('initial generation budget', 2048, kwargs['max_new_tokens'])

    def test_korean_fallback(self) -> None:
        """Missing soynlp preserves space-based Korean alignment and warns once."""
        processor = SimpleNamespace(ko_tokenizer=None)
        model = SimpleNamespace(forced_aligner=SimpleNamespace(aligner_processor=processor))
        with patch.object(qwen_worker.importlib.util, 'find_spec', return_value=None):
            self.worker.InstallKoreanTokenizerFallback(model)
        tokenizer = processor.ko_tokenizer
        assert tokenizer is not None
        with self.assertLogs(level='WARNING') as logs:
            tokens = tokenizer.tokenize('one two')
            tokenizer.tokenize('three')
        self.assertLoggedEqual('space tokens', ['one', 'two'], tokens)
        self.assertLoggedEqual('single warning', 1, len(logs.records))

    @skip_if_debugger_attached
    def test_device_selection(self) -> None:
        """All GPU backends retain their priority, and all CPU paths require consent."""
        for cuda, mps, xpu, expected in ((True, True, True, 'cuda:0'), (False, True, True, 'mps'),
                                          (False, False, True, 'xpu:0'), (False, False, False, 'cpu')):
            torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: cuda),
                                    backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps, is_built=lambda: mps)),
                                    xpu=SimpleNamespace(is_available=lambda: xpu))
            self.assertLoggedEqual('automatic device priority', expected, self.worker.SelectDevice(torch, 'auto', True))
            for candidate in ('cpu', 'cuda', 'mps', 'xpu', 'auto'):
                if candidate == 'cpu' or (candidate == 'auto' and expected == 'cpu') or (
                        candidate == 'cuda' and not cuda) or (candidate == 'mps' and not mps) or (candidate == 'xpu' and not xpu):
                    with self.assertRaises(RuntimeError):
                        self.worker.SelectDevice(torch, candidate, False)
                    self.assertLoggedEqual('consented CPU fallback', 'cpu', self.worker.SelectDevice(torch, candidate, True))


@unittest.skipUnless(QWEN_TEST_ENVIRONMENT and QWEN_TEST_AUDIO, 'Set QWEN_TEST_ENVIRONMENT and QWEN_TEST_AUDIO to run the real Qwen worker')
class TestQwenWorkerIntegration(LoggedTestCase):
    """Run the installed runtime on a short excerpt without importing its SDK in the app."""

    def test_real_worker(self) -> None:
        """The worker loads its models, transcribes a WAV and shuts down cleanly."""
        if not HasQwenRuntime(Path(QWEN_TEST_ENVIRONMENT)):
            self.skipTest('Configured environment does not contain the Qwen runtime')
        if not Path(QWEN_TEST_AUDIO).is_file():
            self.skipTest('Configured test audio does not exist')
        settings = SettingsType({'qwen_installation_directory': QWEN_TEST_ENVIRONMENT, 'device': 'auto',
                                 'max_new_tokens': 2048, 'language': 'Chinese'})
        client = QwenLocalClient(settings)
        self.addCleanup(client.AbortTranscription)
        start = timedelta(seconds=float(os.getenv('QWEN_TEST_START_SECONDS', '0')))
        audio = AudioExtractor().ReadChunkBytes(QWEN_TEST_AUDIO, start, start + timedelta(seconds=20))
        result = client.TranscribeChunk(audio, 'wav')
        self.assertLoggedIsInstance('application result', result, TranscriptionResult)
        self.assertLoggedGreater('transcript length', len(result.text), 0)
        self.assertLoggedGreater('forced aligner stamps', len(result.words), 0)
        self.assertLoggedIsNotNone('detected language', result.language)
        worker = client._worker
        assert worker is not None
        self.assertLoggedTrue('worker remains loaded across chunks', worker.running)
        worker.Shutdown()
        self.assertLoggedFalse('worker shut down', worker.running)
