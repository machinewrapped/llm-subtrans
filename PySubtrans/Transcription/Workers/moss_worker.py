"""Standalone MOSS runtime; stdout is reserved for the JSON-line protocol."""

import sys

_channel = sys.stdout
if __name__ == '__main__':
    # SDK imports may print immediately, so redirect before loading any of them.
    sys.stdout = sys.stderr

import copy
import importlib
import json
import logging
import time
from collections.abc import Callable
from typing import Any

# A chunk takes minutes to transcribe, so report generation progress at this interval
PROGRESS_INTERVAL_SECONDS = 30.0

# Progress is diagnostic, so it is sent at DEBUG while library loggers stay at INFO
_progress_logger = logging.getLogger('moss_worker.progress')
_progress_logger.setLevel(logging.DEBUG)


class MossWorker:
    """Load the MOSS model and processor in their own Python environment."""

    def __init__(self) -> None:
        self.model : Any = None
        self.processor : Any = None
        self.device : Any = None
        self.dtype : Any = None

    def Load(self, message : dict[str, Any]) -> dict[str, Any]:
        """Load the model from the package's own classes, so no code is downloaded with the weights.

        Weights load in their stored dtype before the cast, which matches the package's reference loader.
        """
        torch = importlib.import_module('torch')
        transformers = importlib.import_module('transformers')
        hub = importlib.import_module('huggingface_hub')
        moss = importlib.import_module('moss_transcribe_diarize')

        device = self.SelectDevice(torch, message.get('device', 'auto'), message.get('allow_cpu_fallback', False))
        dtype = self.SelectDtype(torch, device)

        model_id = message['model']
        revision = message['revision']

        model = moss.MossTranscribeDiarizeForConditionalGeneration.from_pretrained(
            model_id, revision=revision, dtype='auto', attn_implementation='sdpa')
        self.model = model.to(dtype=dtype).to(device).eval()

        # AutoTokenizer resolves the tokenizer through the model config, which needs the model repository's code.
        # The tokenizer, feature extractor and processor settings are loaded directly instead.
        tokenizer = transformers.Qwen2Tokenizer.from_pretrained(model_id, revision=revision)
        feature_extractor = transformers.AutoFeatureExtractor.from_pretrained(model_id, revision=revision)

        with open(hub.hf_hub_download(model_id, 'processor_config.json', revision=revision), encoding='utf-8') as stream:
            processor_settings = {key: value for key, value in json.load(stream).items()
                                  if key not in ('processor_class', 'auto_map')}

        with open(hub.hf_hub_download(model_id, 'chat_template.jinja', revision=revision), encoding='utf-8') as stream:
            chat_template = stream.read()

        self.processor = moss.MossTranscribeDiarizeProcessor(
            feature_extractor=feature_extractor, tokenizer=tokenizer, chat_template=chat_template, **processor_settings)

        self.device = torch.device(device)
        self.dtype = dtype
        return {'type': 'ready', 'device': device}

    def Transcribe(self, message : dict[str, Any], send : Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        """
        Send each segment as soon as it is complete, then return them all, with whether generation stopped at its token budget.
        This mirrors the package's generate_transcription, which only reports a token count.
        """
        if self.model is None:
            raise RuntimeError('Load a model before transcription')

        torch = importlib.import_module('torch')
        inference = importlib.import_module('moss_transcribe_diarize.inference_utils')
        moss = importlib.import_module('moss_transcribe_diarize')

        max_new_tokens = int(message['max_new_tokens'])
        messages = inference.build_transcription_messages(message['path'])

        with self._Precision(torch):
            inputs = inference.prepare_inputs(self.processor, messages, device=self.device).to(self.device)

        generation_config = copy.deepcopy(self.model.generation_config)
        generation_config.max_new_tokens = max_new_tokens
        generation_config.do_sample = False

        streamer = _SegmentStreamer(self.processor.tokenizer, moss.TranscriptStreamParser(), send)

        with torch.inference_mode(), self._Precision(torch):
            self.model.generate(
                input_ids=inputs['input_ids'], attention_mask=inputs['attention_mask'],
                input_features=inputs['input_features'], audio_feature_lengths=inputs['audio_feature_lengths'],
                audio_chunk_mapping=inputs['audio_chunk_mapping'], generation_config=generation_config,
                streamer=streamer)

        segments = streamer.Finish()
        return {'type': 'result', 'segments': segments, 'tokens': streamer.generated_tokens,
                'stopped_at_limit': streamer.generated_tokens >= max_new_tokens}

    def _Precision(self, torch : Any) -> Any:
        """Autocast to half precision on CUDA, as the package does."""
        if self.device.type == 'cuda' and self.dtype in (torch.float16, torch.bfloat16):
            return torch.amp.autocast('cuda', dtype=self.dtype)

        return torch.no_grad()

    @staticmethod
    def SelectDtype(torch : Any, device : str) -> Any:
        """bfloat16 on CUDA, float16 on MPS and XPU, and float32 on CPU, as the package's own runner does."""
        if device == 'cpu':
            return torch.float32

        return torch.float16 if device.startswith(('mps', 'xpu')) else torch.bfloat16

    @staticmethod
    def SelectDevice(torch : Any, configured : str, allow_cpu_fallback : bool) -> str:
        """Preserve accelerator priority and require consent for every CPU path."""
        configured = configured.strip().casefold()
        if configured not in ('auto', 'cuda', 'mps', 'xpu', 'cpu'):
            logging.warning("Unknown device '%s', using automatic selection", configured)
            configured = 'auto'

        if configured == 'cpu':
            if not allow_cpu_fallback:
                raise RuntimeError("CPU inference is disabled. Enable 'allow_cpu_fallback' in MOSS Local advanced settings.")
            return 'cpu'

        candidates = ('cuda', 'mps', 'xpu') if configured == 'auto' else (configured,)
        for candidate in candidates:
            if candidate == 'cuda' and torch.cuda.is_available():
                # AMD ROCm exposes the CUDA API too.
                return 'cuda:0'

            mps = getattr(torch.backends, 'mps', None)
            if candidate == 'mps' and mps is not None and mps.is_available() and mps.is_built():
                return 'mps'

            xpu = getattr(torch, 'xpu', None)
            if candidate == 'xpu' and xpu is not None and xpu.is_available():
                return 'xpu:0'

        if allow_cpu_fallback:
            return 'cpu'

        raise RuntimeError("No requested hardware accelerator is available. Enable 'allow_cpu_fallback' in MOSS Local advanced settings to permit CPU inference.")


class _SegmentStreamer:
    """
    Decode tokens as generate() produces them, and send each transcript segment once it is complete.
    The segments it parses are the result, so those sent always lead the final list.
    """

    def __init__(self, tokenizer : Any, parser : Any, send : Callable[[dict[str, Any]], None]) -> None:
        self.tokenizer : Any = tokenizer
        self.parser : Any = parser
        self.send : Callable[[dict[str, Any]], None] = send
        self.segments : list[dict[str, Any]] = []
        self.generated_tokens : int = 0
        self.started : float = time.monotonic()
        self.reported : float = self.started
        self._pending : list[int] = []
        self._seen_prompt : bool = False

    def put(self, value : Any) -> None:
        """Called by generate() with the prompt first, then with each new token."""
        if not self._seen_prompt:
            self._seen_prompt = True
            return

        tokens = value.reshape(-1).tolist()
        self.generated_tokens += len(tokens)
        self._pending.extend(tokens)

        # Only the tokens not yet decoded are decoded, so the cost stays linear in the transcript length.
        # A character split across tokens decodes as a replacement mark until its last token arrives.
        text = self.tokenizer.decode(self._pending, skip_special_tokens=True)
        if not text.endswith('�'):
            self._pending = []
            self._Feed(text)

        now = time.monotonic()
        if now - self.reported >= PROGRESS_INTERVAL_SECONDS:
            self.reported = now
            _progress_logger.debug('Generated %d tokens in %.0f s', self.generated_tokens, now - self.started)

    def end(self) -> None:
        """Called by generate() when generation stops."""
        if self._pending:
            self._Feed(self.tokenizer.decode(self._pending, skip_special_tokens=True))
            self._pending = []

    def Finish(self) -> list[dict[str, Any]]:
        """Complete the final segment and return them all."""
        self.end()
        for segment in self.parser.close():
            self.segments.append(self._Segment(segment))

        return self.segments

    def _Feed(self, text : str) -> None:
        """Parse more transcript text, sending any segments it completes."""
        for segment in self.parser.feed(text):
            data = self._Segment(segment)
            self.segments.append(data)
            self.send({'type': 'segment', 'segment': data})

    @staticmethod
    def _Segment(segment : Any) -> dict[str, Any]:
        """The protocol form of a parsed segment."""
        return {'start': segment.start, 'end': segment.end, 'speaker': segment.speaker, 'text': segment.text}


def _Send(message : dict[str, Any]) -> None:
    """Write one protocol message to the host."""
    _channel.write(json.dumps(message, ensure_ascii=True, allow_nan=False) + '\n')
    _channel.flush()


def Main() -> None:
    """Serve one request at a time; all failures use the same error envelope."""
    logging.basicConfig(level=logging.INFO, format='SUBTRANS_WORKER %(levelname)s %(message)s')
    worker = MossWorker()

    for line in sys.stdin:
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError('Expected a JSON object')

            kind = message.get('type')
            if kind == 'shutdown':
                return
            if kind == 'load':
                if worker.model is not None:
                    raise RuntimeError('A model is already loaded; start a new worker to replace it')
                response = worker.Load(message)
            elif kind == 'transcribe':
                response = worker.Transcribe(message, _Send)
            else:
                raise ValueError('Unknown request type')
        except Exception as error:
            response = {'type': 'error', 'error_type': type(error).__name__, 'message': str(error)}

        _Send(response)


if __name__ == '__main__':
    Main()
