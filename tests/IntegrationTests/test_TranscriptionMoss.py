"""MOSS provider integration and an opt-in real worker smoke test.

Set MOSS_TEST_ENVIRONMENT to a MOSS venv and MOSS_TEST_AUDIO to speech media.
MOSS_TEST_START_SECONDS optionally selects the beginning of the 30-second excerpt.
"""

import io
import json
import os
import sys
from contextlib import nullcontext
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, mock_open, patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import skip_if_debugger_attached
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.AudioExtractor import AudioExtractor
from PySubtrans.Transcription.Providers.Clients import MossLocalClient as client_module
from PySubtrans.Transcription.Providers.Clients.MossLocalClient import MossLocalClient
from PySubtrans.Transcription.Providers.Provider_MossLocal import MossLocalProvider
from PySubtrans.Transcription.Torch.MossRuntime import HasMossRuntime
from PySubtrans.Transcription.TranscriptionProvider import OptionsScope, TranscriptionProvider
from PySubtrans.Transcription.WorkerHost import WorkerError
from PySubtrans.Transcription.Workers import moss_worker

HAS_MOSS_RUNTIME = 'PySubtrans.Transcription.Providers.Provider_MossLocal.HasMossRuntime'
MOSS_TEST_ENVIRONMENT = os.getenv('MOSS_TEST_ENVIRONMENT', '')
MOSS_TEST_AUDIO = os.getenv('MOSS_TEST_AUDIO', '')


class _Tokens:
    """A tensor of token ids, here strings so the fake tokenizer can join them."""

    def __init__(self, tokens : list[str]) -> None:
        self.tokens : list[str] = tokens

    def reshape(self, *_shape : int) -> '_Tokens':
        return self

    def tolist(self) -> list[str]:
        return self.tokens


class _FakeTokenizer:
    """Joins tokens, decoding a lone replacement mark as an incomplete character, like a byte-level tokenizer."""

    def decode(self, tokens : list[str], skip_special_tokens : bool = False) -> str:
        text = ''.join(tokens)
        return text.replace('�é', 'é')


class _FakeParser:
    """Treats '|' as the end of a segment."""

    def __init__(self) -> None:
        self.text : str = ''
        self._current : str = ''

    def feed(self, text : str) -> list[SimpleNamespace]:
        self.text += text
        segments = []
        for character in text:
            if character == '|':
                segments.append(self._Segment())
            else:
                self._current += character
        return segments

    def close(self) -> list[SimpleNamespace]:
        return [self._Segment()] if self._current else []

    def _Segment(self) -> SimpleNamespace:
        segment = SimpleNamespace(start=0.0, end=1.0, speaker='S01', text=self._current)
        self._current = ''
        return segment


class TestMossLocalProvider(LoggedTestCase):
    """Provider registration, options and validation, with the runtime check mocked."""

    def test_registered(self) -> None:
        """MOSS Local registers without importing its SDK."""
        self.assertLoggedIn("moss present", "MOSS Local", TranscriptionProvider.get_providers())

    def test_options_progressive_disclosure_without_runtime(self) -> None:
        """Only the environment directory is offered until the runtime is found."""
        provider = MossLocalProvider(SettingsType())
        with patch(HAS_MOSS_RUNTIME, return_value=False):
            options = provider.GetOptions(provider.settings)
            per_run = provider.GetOptions(provider.settings, OptionsScope.PER_RUN)
            valid = provider.ValidateSettings()

        self.assertLoggedEqual("only the directory option", ['moss_installation_directory'], list(options))
        self.assertLoggedEqual("nothing per run", 0, len(per_run))
        self.assertLoggedFalse("invalid without runtime", valid)

    def test_options_with_runtime(self) -> None:
        """A found runtime offers diarization per run, and machine settings only in the full scope."""
        provider = MossLocalProvider(SettingsType())
        with patch(HAS_MOSS_RUNTIME, return_value=True):
            options = provider.GetOptions(provider.settings)
            per_run = provider.GetOptions(provider.settings, OptionsScope.PER_RUN)

        for key in ('diarize', 'device', 'max_new_tokens', 'allow_cpu_fallback', 'moss_installation_directory'):
            self.assertLoggedIn(f"{key} option", key, options)
        self.assertLoggedIn("diarize per run", 'diarize', per_run)
        self.assertLoggedNotIn("no language hint", 'language', options)
        self.assertLoggedNotIn("directory is not a per-run choice", 'moss_installation_directory', per_run)

    def test_source_install_uses_default_environment(self) -> None:
        """Without a directory a source install checks envmoss beside the application."""
        provider = MossLocalProvider(SettingsType())
        with patch(HAS_MOSS_RUNTIME, return_value=True) as has_runtime, patch.object(sys, 'frozen', False, create=True):
            valid = provider.ValidateSettings()

        self.assertLoggedTrue("valid with default environment", valid)
        self.assertLoggedEqual("default environment checked", 'envmoss', has_runtime.call_args.args[0].name)

    def test_frozen_build_requires_directory(self) -> None:
        """A packaged build has no default environment to find."""
        provider = MossLocalProvider(SettingsType())
        with patch(HAS_MOSS_RUNTIME, return_value=True), patch.object(sys, 'frozen', True, create=True):
            self.assertLoggedFalse("invalid without directory", provider.ValidateSettings())

    def test_chunks_limited_by_context(self) -> None:
        """Chunk settings that could plan a chunk longer than the model's context allows are rejected before a run starts."""
        cases = [
            ("long maximum", {'max_chunk_seconds': 2400.0}),
            ("maximum leaves no room for the lookahead", {'max_chunk_seconds': 1200.0}),
        ]
        for label, settings in cases:
            provider = MossLocalProvider(SettingsType(settings))
            with patch(HAS_MOSS_RUNTIME, return_value=True):
                self.assertLoggedFalse(label, provider.ValidateSettings())

    def test_language_hint_ignored(self) -> None:
        """The model takes no language hint, so every hint resolves to auto-detection."""
        provider = MossLocalProvider(SettingsType())

        self.assertLoggedIsNone("hint dropped", provider.ResolveLanguageCode('Spanish'))

    def test_diarization_follows_setting(self) -> None:
        """Turning diarization off means the speaker-aware line options no longer apply."""
        self.assertLoggedTrue("diarizes", MossLocalProvider(SettingsType()).supports_diarization)
        self.assertLoggedFalse("speakers off", MossLocalProvider(SettingsType({'diarize': False})).supports_diarization)


class TestMossResultMapping(LoggedTestCase):
    """Worker segments become chunk-relative parts."""

    _RESPONSE = {'type': 'result', 'tokens': 40, 'stopped_at_limit': False, 'segments': [
        {'start': 0.1, 'end': 1.61, 'speaker': 'S01', 'text': ' first '},
        {'start': 1.63, 'end': 3.64, 'speaker': 'S02', 'text': 'second'},
        {'start': 4.0, 'end': 5.0, 'speaker': 'S01', 'text': '   '},
        {'start': 6.0, 'end': 5.0, 'speaker': 'S01', 'text': 'reversed'},
        {'start': None, 'end': 7.0, 'speaker': 'S01', 'text': 'untimed'},
    ]}

    def test_segments_become_parts(self) -> None:
        """Timed, non-empty segments keep their order, timing and speaker."""
        result = MossLocalClient.ParseResult(self._RESPONSE)

        self.assertLoggedEqual("usable parts", 2, len(result.parts))
        self.assertLoggedEqual("text trimmed", 'first', result.parts[0].text)
        self.assertLoggedEqual("start", timedelta(seconds=0.1), result.parts[0].start)
        self.assertLoggedEqual("end", timedelta(seconds=3.64), result.parts[1].end)
        self.assertLoggedEqual("speakers", ['S01', 'S02'], [part.speaker for part in result.parts])
        self.assertLoggedEqual("no words", 0, len(result.words))
        self.assertLoggedGreater("transcript text", len(result.text), 0)

    def test_speakers_dropped_without_diarization(self) -> None:
        """With diarization off no part carries a speaker."""
        result = MossLocalClient.ParseResult(self._RESPONSE, diarize=False)

        self.assertLoggedEqual("no speakers", [None, None], [part.speaker for part in result.parts])

    def test_silence_has_no_text(self) -> None:
        """A chunk with no speech has no parts and empty text, so the coordinator skips it."""
        result = MossLocalClient.ParseResult({'type': 'result', 'segments': []})

        self.assertLoggedEqual("empty text", '', result.text)

    @skip_if_debugger_attached
    def test_malformed_results(self) -> None:
        """Payloads of the wrong shape are worker errors."""
        for response in ({'type': 'result'}, {'type': 'result', 'segments': ['text']}):
            with self.assertRaises(WorkerError):
                MossLocalClient.ParseResult(response)


class TestMossWorkerSession(LoggedTestCase):
    """Model cache, requests and abort use fake hosts and never write temporary chunks."""

    def setUp(self) -> None:
        super().setUp()
        self.state = patch.multiple(client_module, _loaded_worker=None, _loaded_key=None, _loaded_device=None)
        self.state.start()
        self.addCleanup(self.state.stop)
        self.resolve = patch.object(client_module, 'ResolveEnvironmentPython', return_value='python')
        self.resolve.start()
        self.addCleanup(self.resolve.stop)
        self.hosts : list[Mock] = []

        def Host(*args : Any) -> Mock:
            host = Mock()
            host.running = True
            host.Request.return_value = {'type': 'ready', 'device': 'cuda:0'}
            self.hosts.append(host)
            return host

        self.factory = patch.object(client_module, 'WorkerHost', side_effect=Host)
        self.factory.start()
        self.addCleanup(self.factory.stop)

    def test_cache_and_eviction(self) -> None:
        """Budget and diarization changes reuse the worker; device and environment changes replace it."""
        worker = MossLocalClient(SettingsType())._LoadWorker()
        again = MossLocalClient(SettingsType({'max_new_tokens': 4096, 'diarize': False}))
        self.assertLoggedIs("same model reused", worker, again._LoadWorker())

        for setting in ({'device': 'cpu'}, {'allow_cpu_fallback': True}):
            previous = self.hosts[-1]
            MossLocalClient(SettingsType(setting))._LoadWorker()
            self.assertLoggedEqual("old worker shut down", 1, previous.Shutdown.call_count)

        with patch.object(client_module, 'ResolveEnvironmentPython', return_value='different-python'):
            MossLocalClient(SettingsType())._LoadWorker()
        self.assertLoggedEqual("replacement per load change", 4, len(self.hosts))

    def test_load_pins_model_revision(self) -> None:
        """The worker loads a fixed model revision."""
        MossLocalClient(SettingsType())._LoadWorker()
        request = self.hosts[-1].Request.call_args.args[0]

        self.assertLoggedEqual("load request", 'load', request['type'])
        self.assertLoggedIn("revision sent", 'revision', request)

    def test_request_and_chunk_cleanup(self) -> None:
        """Each call sends its current budget, then removes the WAV."""
        client = MossLocalClient(SettingsType({'max_new_tokens': 4096}))
        client._LoadWorker()
        worker = self.hosts[-1]
        worker.Request.return_value = {'type': 'result', 'segments': [{'start': 0, 'end': 1, 'speaker': 'S01', 'text': 'hi'}],
                                       'tokens': 10, 'stopped_at_limit': False}

        with patch.object(client, '_WriteChunk', return_value='chunk.wav'), patch.object(client_module.os, 'remove') as remove:
            result = client.TranscribeChunk(b'audio', 'wav')

        self.assertLoggedEqual("generation budget", 4096, worker.Request.call_args.args[0]['max_new_tokens'])
        self.assertLoggedEqual("one part", 1, len(result.parts))
        self.assertLoggedEqual("WAV removed", 1, remove.call_count)

    def test_streamed_segments_reported(self) -> None:
        """Segments the worker streams are reported as parts, and match the leading parts of the result."""
        client = MossLocalClient(SettingsType())
        client._LoadWorker()
        segments = [{'start': 0, 'end': 1, 'speaker': 'S01', 'text': 'hi'}, {'start': 1, 'end': 1, 'speaker': 'S01', 'text': ' '},
                    {'start': 2, 'end': 3, 'speaker': 'S02', 'text': 'there'}]

        def Request(message : dict[str, Any], expected : str, on_segment : Any = None, on_progress : Any = None) -> dict[str, Any]:
            for segment in segments[:2]:
                on_segment({'type': 'segment', 'segment': segment})
            return {'type': 'result', 'segments': segments, 'tokens': 10, 'stopped_at_limit': False}

        self.hosts[-1].Request.side_effect = Request
        reported : list[Any] = []

        with patch.object(client, '_WriteChunk', return_value='chunk.wav'), patch.object(client_module.os, 'remove'):
            result = client.TranscribeChunk(b'audio', 'wav', reported.append)

        self.assertLoggedEqual("usable streamed segment reported", 1, len(reported))
        self.assertLoggedEqual("reported parts lead the result", reported, result.parts[:len(reported)])

    def test_token_limit_warns(self) -> None:
        """A chunk that stopped at its token budget is reported, since its end may be missing."""
        client = MossLocalClient(SettingsType())
        client._LoadWorker()
        self.hosts[-1].Request.return_value = {'type': 'result', 'segments': [], 'tokens': 32768, 'stopped_at_limit': True}

        with patch.object(client, '_WriteChunk', return_value='chunk.wav'), patch.object(client_module.os, 'remove'):
            with self.assertLogs(level='WARNING'):
                client.TranscribeChunk(b'audio', 'wav')

    @skip_if_debugger_attached
    def test_failed_request_cleans_chunk(self) -> None:
        """Temporary audio is removed after a runtime failure too, and the worker is stopped."""
        client = MossLocalClient(SettingsType())
        client._LoadWorker()
        worker = self.hosts[-1]
        worker.Request.side_effect = WorkerError('failure')

        with patch.object(client, '_WriteChunk', return_value='chunk.wav'), patch.object(client_module.os, 'remove') as remove:
            with self.assertRaises(WorkerError):
                client.TranscribeChunk(b'audio', 'wav')

        self.assertLoggedEqual("failed WAV removed", 1, remove.call_count)
        self.assertLoggedEqual("worker aborted", 1, worker.Abort.call_count)

    @skip_if_debugger_attached
    def test_abort(self) -> None:
        """Abort stops the worker and refuses further chunks."""
        client = MossLocalClient(SettingsType())
        client._LoadWorker()
        client.AbortTranscription()

        self.assertLoggedGreater("worker aborted", self.hosts[-1].Abort.call_count, 0)
        with self.assertRaises(SubtitleError):
            client.TranscribeChunk(b'audio', 'wav')


class TestMossWorkerRuntime(LoggedTestCase):
    """The MOSS package and Torch are represented by in-memory objects."""

    def test_transcribe_streams_segments(self) -> None:
        """Each segment is sent once complete, and all are returned with whether the budget was reached."""
        inputs = {key: key for key in ('input_ids', 'attention_mask', 'input_features', 'audio_feature_lengths', 'audio_chunk_mapping')}
        inference = SimpleNamespace(
            build_transcription_messages=Mock(return_value=['messages']),
            prepare_inputs=Mock(return_value=SimpleNamespace(to=lambda _device: inputs)))
        package = SimpleNamespace(TranscriptStreamParser=_FakeParser)
        torch = SimpleNamespace(inference_mode=nullcontext, no_grad=nullcontext, float16='fp16', bfloat16='bf16')
        modules = {'torch': torch, 'moss_transcribe_diarize.inference_utils': inference, 'moss_transcribe_diarize': package}

        def Generate(**kwargs : Any) -> None:
            streamer = kwargs['streamer']
            for tokens in (['prompt'], ['he'], ['llo|'], ['wor'], ['ld']):
                streamer.put(_Tokens(tokens))
            streamer.end()

        worker = moss_worker.MossWorker()
        worker.model = Mock(generation_config=SimpleNamespace(), generate=Mock(side_effect=Generate))
        worker.processor = SimpleNamespace(tokenizer=_FakeTokenizer())
        worker.device = SimpleNamespace(type='cpu')
        sent : list[dict[str, Any]] = []

        with patch.object(moss_worker.importlib, 'import_module', side_effect=modules.__getitem__):
            response = worker.Transcribe({'path': 'chunk.wav', 'max_new_tokens': 4}, sent.append)

        self.assertLoggedEqual("completed segment sent", ['hello'], [message['segment']['text'] for message in sent])
        self.assertLoggedEqual("all segments returned", ['hello', 'world'], [segment['text'] for segment in response['segments']])
        self.assertLoggedTrue("stopped at limit", response['stopped_at_limit'])
        self.assertLoggedEqual("budget passed on", 4, worker.model.generate.call_args.kwargs['generation_config'].max_new_tokens)

    def test_split_character_waits_for_its_last_token(self) -> None:
        """Text is only parsed once a character split across tokens is complete."""
        parser = _FakeParser()
        streamer = moss_worker._SegmentStreamer(_FakeTokenizer(), parser, Mock())

        for tokens in (['prompt'], ['caf'], ['�'], ['é']):
            streamer.put(_Tokens(tokens))

        self.assertLoggedEqual("whole character parsed", 'café', parser.text)
        self.assertLoggedEqual("every token counted", 3, streamer.generated_tokens)

    def test_tokenizer_loads_from_cache(self) -> None:
        """The tokenizer's files are fetched at the pinned revision, then it loads from the cache, so it makes no Hub queries of its own."""
        hub = SimpleNamespace(hf_hub_download=Mock(return_value='file'))
        transformers = SimpleNamespace(Qwen2Tokenizer=Mock(), AutoFeatureExtractor=Mock())
        package = SimpleNamespace(MossTranscribeDiarizeForConditionalGeneration=Mock(), MossTranscribeDiarizeProcessor=Mock())
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True), backends=SimpleNamespace(),
                                bfloat16='bf16', device=Mock())
        modules = {'torch': torch, 'transformers': transformers, 'huggingface_hub': hub, 'moss_transcribe_diarize': package}

        # open is patched first, since resolving its module goes through import_module
        with patch('builtins.open', mock_open(read_data='{}')), \
                patch.object(moss_worker.importlib, 'import_module', side_effect=modules.__getitem__):
            moss_worker.MossWorker().Load({'model': 'model', 'revision': 'pinned', 'device': 'auto'})

        downloaded = {call.args[1] for call in hub.hf_hub_download.call_args_list if call.kwargs.get('revision') == 'pinned'}
        self.assertLoggedTrue("tokenizer files fetched at the revision", set(moss_worker.TOKENIZER_FILES) <= downloaded)
        self.assertLoggedTrue("tokenizer loaded from the cache", transformers.Qwen2Tokenizer.from_pretrained.call_args.kwargs['local_files_only'])

    def test_device_and_dtype(self) -> None:
        """Accelerators are preferred, CPU needs consent, and CPU runs in float32."""
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False), backends=SimpleNamespace(),
                                bfloat16='bf16', float16='fp16', float32='fp32')

        self.assertLoggedEqual("CPU with consent", 'cpu', moss_worker.MossWorker.SelectDevice(torch, 'auto', True))
        self.assertLoggedEqual("float32 on CPU", 'fp32', moss_worker.MossWorker.SelectDtype(torch, 'cpu'))
        self.assertLoggedEqual("bfloat16 on CUDA", 'bf16', moss_worker.MossWorker.SelectDtype(torch, 'cuda:0'))

    @skip_if_debugger_attached
    def test_cpu_needs_consent(self) -> None:
        """Without consent there is no CPU path."""
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False), backends=SimpleNamespace())

        for device in ('auto', 'cpu'):
            with self.assertRaises(RuntimeError):
                moss_worker.MossWorker.SelectDevice(torch, device, False)

    def test_protocol_service(self) -> None:
        """Malformed requests and runtime failures return errors without corrupting the channel."""
        requests = io.StringIO('not JSON\n{"type":"unknown"}\n{"type":"load"}\n{"type":"transcribe"}\n{"type":"shutdown"}\n')
        channel = io.StringIO()
        fake = Mock()
        fake.model = None
        fake.Load.return_value = {'type': 'ready', 'device': 'cpu'}
        fake.Transcribe.side_effect = ValueError('SDK failure')

        with patch.object(moss_worker.sys, 'stdin', requests), patch.object(moss_worker, '_channel', channel), \
                patch.object(moss_worker, 'MossWorker', return_value=fake):
            moss_worker.Main()

        responses = [json.loads(line) for line in channel.getvalue().splitlines()]
        self.assertLoggedEqual("protocol sequence", ['error', 'error', 'ready', 'error'], [response['type'] for response in responses])


class TestMossWorkerIntegration(LoggedTestCase):
    """Run the installed runtime on a short excerpt without importing its SDK in the app."""

    def test_real_worker(self) -> None:
        """The worker loads the model, transcribes a WAV and shuts down cleanly."""
        if not MOSS_TEST_ENVIRONMENT or not HasMossRuntime(Path(MOSS_TEST_ENVIRONMENT)):
            self.skipTest('Set MOSS_TEST_ENVIRONMENT to an environment with the MOSS runtime')
        if not Path(MOSS_TEST_AUDIO).is_file():
            self.skipTest('Set MOSS_TEST_AUDIO to speech media')

        client = MossLocalClient(SettingsType({'moss_installation_directory': MOSS_TEST_ENVIRONMENT, 'max_new_tokens': 4096}))
        self.addCleanup(client.AbortTranscription)

        start = timedelta(seconds=float(os.getenv('MOSS_TEST_START_SECONDS', '0')))
        audio = AudioExtractor().ReadChunkBytes(MOSS_TEST_AUDIO, start, start + timedelta(seconds=30))
        result = client.TranscribeChunk(audio, 'wav')

        self.assertLoggedGreater("parts", len(result.parts), 0)
        self.assertLoggedTrue("speakers labelled", any(part.speaker for part in result.parts))

        worker = client._worker
        assert worker is not None
        self.assertLoggedTrue("worker remains loaded across chunks", worker.running)
        worker.Shutdown()
        self.assertLoggedFalse("worker shut down", worker.running)
