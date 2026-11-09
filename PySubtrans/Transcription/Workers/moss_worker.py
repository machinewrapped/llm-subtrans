"""Standalone MOSS runtime; stdout is reserved for the JSON-line protocol."""

import sys

_channel = sys.stdout
if __name__ == '__main__':
    # SDK imports may print immediately, so redirect before loading any of them.
    sys.stdout = sys.stderr

import importlib
import json
import logging
import time
from typing import Any

# A chunk takes minutes to transcribe, so report generation progress at this interval
PROGRESS_INTERVAL_SECONDS = 30.0


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

    def Transcribe(self, message : dict[str, Any]) -> dict[str, Any]:
        """Return the parsed segments, with whether generation stopped at its token budget."""
        if self.model is None:
            raise RuntimeError('Load a model before transcription')

        inference = importlib.import_module('moss_transcribe_diarize.inference_utils')
        moss = importlib.import_module('moss_transcribe_diarize')

        max_new_tokens = int(message['max_new_tokens'])
        progress = _ProgressLog()

        result = inference.generate_transcription(
            self.model, self.processor, inference.build_transcription_messages(message['path']),
            max_new_tokens=max_new_tokens, do_sample=False, device=self.device, dtype=self.dtype,
            token_callback=progress.Update,
        )

        generated = int(result['generated_tokens'])
        segments = [
            {'start': segment.start, 'end': segment.end, 'speaker': segment.speaker, 'text': segment.text}
            for segment in moss.parse_transcript(result['text'])
        ]

        return {'type': 'result', 'segments': segments, 'tokens': generated,
                'stopped_at_limit': generated >= max_new_tokens}

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


class _ProgressLog:
    """Log the number of generated tokens now and then, since the protocol has no progress message."""

    def __init__(self) -> None:
        self.started : float = time.monotonic()
        self.reported : float = self.started

    def Update(self, generated_tokens : int) -> None:
        """Called for every generated token."""
        now = time.monotonic()
        if now - self.reported >= PROGRESS_INTERVAL_SECONDS:
            self.reported = now
            logging.info('Generated %d tokens in %.0f s', generated_tokens, now - self.started)


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
                response = worker.Transcribe(message)
            else:
                raise ValueError('Unknown request type')
        except Exception as error:
            response = {'type': 'error', 'error_type': type(error).__name__, 'message': str(error)}

        _channel.write(json.dumps(response, ensure_ascii=True, allow_nan=False) + '\n')
        _channel.flush()


if __name__ == '__main__':
    Main()
