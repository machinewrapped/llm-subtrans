"""Standalone Qwen runtime; stdout is reserved for the JSON-line protocol."""

import sys

_channel = sys.stdout
if __name__ == '__main__':
    # SDK imports may print immediately, so redirect before loading any of them.
    sys.stdout = sys.stderr

import importlib
import importlib.util
import json
import logging
from typing import Any


class SpaceSplitKoreanTokenizer:
    """Keep Korean alignment usable when a hand-built environment lacks soynlp."""

    def __init__(self) -> None:
        self._warned : bool = False

    def tokenize(self, text : str) -> list[str]:
        """Implement the SDK tokenizer interface, warning once about precision."""
        if not self._warned:
            self._warned = True
            logging.warning('soynlp is not installed; aligning Korean text on spaces instead')

        return text.split()


class QwenWorker:
    """Load one ASR model and forced aligner in their own Python environment."""

    def __init__(self) -> None:
        self.model : Any = None

    def Load(self, message : dict[str, Any]) -> dict[str, Any]:
        """Import the optional SDK only after the channel has been redirected.

        These lazy SDK loads preserve the existing Qwen loading policy.
        The standalone worker never imports application or GUI modules.
        """
        torch = importlib.import_module('torch')
        qwen = importlib.import_module('qwen_asr')
        utils = importlib.import_module('qwen_asr.inference.utils')

        device = self.SelectDevice(torch, message.get('device', 'auto'), message.get('allow_cpu_fallback', False))

        # MPS and XPU need float16 rather than the bfloat16 used on CUDA and CPU.
        dtype = torch.float16 if device.startswith(('mps', 'xpu')) else torch.bfloat16

        self.model = qwen.Qwen3ASRModel.from_pretrained(
            message['checkpoint'], dtype=dtype, device_map=device,
            max_new_tokens=message['max_new_tokens'], forced_aligner=message['aligner_checkpoint'],
            forced_aligner_kwargs=dict(dtype=dtype, device_map=device),
        )

        self.InstallKoreanTokenizerFallback(self.model)
        return {'type': 'ready', 'device': device, 'supported_languages': list(utils.SUPPORTED_LANGUAGES)}

    def Transcribe(self, message : dict[str, Any]) -> dict[str, Any]:
        """Return unmodified transcript fields and raw word stamps from Qwen."""
        if self.model is None:
            raise RuntimeError('Load a model before transcription')

        model = self.model

        # Read the budget per call so it can change without reloading several GB of models.
        model.max_new_tokens = message['max_new_tokens']
        language = message.get('language')

        # Qwen passes the detected language to its aligner, so auto-detection can still return word stamps.
        want_stamps = message.get('align', True)

        try:
            results = model.transcribe(audio=message['path'], language=language, return_time_stamps=want_stamps)
        except ValueError as error:
            detail = str(error).casefold()
            unsupported = 'unsupported language' in detail or 'language is not supported' in detail
            if not (want_stamps and unsupported):
                raise

            # The ASR model covers languages the forced aligner does not.
            # English alignment is better than losing word timings, with text-only output as a last resort.
            logging.warning('Detected language unsupported by aligner, retrying with English')
            try:
                results = model.transcribe(audio=message['path'], language='English', return_time_stamps=True)
            except ValueError:
                logging.warning('Alignment failed, timestamps will be approximate')
                results = model.transcribe(audio=message['path'], language=language, return_time_stamps=False)

        if not results:
            # Silence and music can return no results; neither is an inference failure.
            return {'type': 'result', 'text': '', 'language': None, 'time_stamps': []}

        result = results[0]
        return {
            'type': 'result', 'text': result.text, 'language': result.language,
            'time_stamps': [dict(text=unit.text, start_time=unit.start_time, end_time=unit.end_time)
                            for unit in getattr(result, 'time_stamps', None) or []],
        }

    @staticmethod
    def SelectDevice(torch : Any, configured : str, allow_cpu_fallback : bool) -> str:
        """Preserve accelerator priority and require consent for every CPU path."""
        configured = configured.strip().casefold()
        if configured not in ('auto', 'cuda', 'mps', 'xpu', 'cpu'):
            logging.warning("Unknown device '%s', using automatic selection", configured)
            configured = 'auto'

        if configured == 'cpu':
            if not allow_cpu_fallback:
                raise RuntimeError("CPU inference is disabled. Enable 'allow_cpu_fallback' in Qwen Local advanced settings.")
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

        raise RuntimeError("No requested hardware accelerator is available. Enable 'allow_cpu_fallback' in Qwen Local advanced settings to permit CPU inference.")

    @staticmethod
    def InstallKoreanTokenizerFallback(model : Any) -> None:
        """Avoid the SDK's deferred soynlp import when it is unavailable."""
        if importlib.util.find_spec('soynlp') is not None:
            return

        # qwen-asr only imports soynlp when ko_tokenizer is unset.
        # Korean uses spaces between words, so a fallback preserves alignment at coarser precision.
        processor = getattr(getattr(model, 'forced_aligner', None), 'aligner_processor', None)
        if processor is not None and hasattr(processor, 'ko_tokenizer') and processor.ko_tokenizer is None:
            processor.ko_tokenizer = SpaceSplitKoreanTokenizer()


def Main() -> None:
    """Serve one request at a time; all failures use the same error envelope."""
    logging.basicConfig(level=logging.INFO, format='SUBTRANS_WORKER %(levelname)s %(message)s')
    worker = QwenWorker()

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
