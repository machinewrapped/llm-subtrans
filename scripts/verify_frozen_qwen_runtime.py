"""Verify the in-process frozen Qwen runtime without loading model weights."""

import argparse
import importlib
import json
import platform
import sys
import traceback
from pathlib import Path

from PySubtrans.SettingsType import SettingsType
from PySubtrans.Transcription.Providers.Clients.QwenLocalClient import QwenLocalClient


def _emit(event : str, **values: object) -> None:
    """Write one flushed, machine-readable evidence record."""
    record: dict[str, object] = {"event": event, **values}
    print(json.dumps(record, sort_keys=True, ensure_ascii=True), flush=True)


def _availability(function : object) -> tuple[bool|None, str|None]:
    """Call an availability function without converting errors into true values."""
    try:
        return (bool(function()), None) if callable(function) else (False, None)
    except Exception as error:
        return None, str(error)


def _module_evidence(module_name : str, external_root : Path, frozen_root : Path|None) -> dict[str, object]:
    """Import a loaded dependency and record its origin without invoking downloads."""
    module = importlib.import_module(module_name)
    origin = str(getattr(module, "__file__", ""))
    origin_path = Path(origin).resolve() if origin else None
    result: dict[str, object] = {
        "name": module_name,
        "file": origin,
        "version": str(getattr(module, "__version__", "unknown")),
        "under_external_torch_root": bool(origin_path and origin_path.is_relative_to(external_root)),
    }
    if frozen_root is not None:
        result["under_frozen_application_root"] = bool(
            origin_path and origin_path.is_relative_to(frozen_root)
        )
    return result


def _default_torch_runtime() -> Path:
    """Resolve the sidecar layout used by the Windows distribution."""
    if bool(getattr(sys, "frozen", False)):
        return Path(sys.executable).resolve().parent / "torch-runtime"
    return Path(__file__).resolve().parents[1] / "envsubtrans" / "Lib" / "site-packages"


def _build_parser() -> argparse.ArgumentParser:
    """Create the probe command-line parser."""
    parser = argparse.ArgumentParser(
        description="Verify frozen Qwen imports with an external Torch sidecar; no model is loaded."
    )
    parser.add_argument(
        "--torch-runtime",
        type=Path,
        default=None,
        help="External Torch root or site-packages directory; defaults to the frozen sidecar.",
    )
    return parser


def main(arguments : list[str]|None = None) -> int:
    """Run the frozen-runtime import probe and return a diagnostic exit code."""
    parser = _build_parser()
    parsed = parser.parse_args(arguments)
    external_root = (parsed.torch_runtime or _default_torch_runtime()).expanduser().resolve()
    frozen_root_value = getattr(sys, "_MEIPASS", None)
    frozen_root = Path(str(frozen_root_value)).resolve() if frozen_root_value else None

    _emit(
        "process",
        sys_frozen=bool(getattr(sys, "frozen", False)),
        executable=str(Path(sys.executable).resolve()),
        frozen_root=str(frozen_root) if frozen_root else None,
        python_version=sys.version,
        platform=platform.platform(),
        configured_torch_runtime=str(external_root),
    )

    try:
        _emit("loader_start", loader="QwenLocalClient.__init__")
        settings = SettingsType({
            "device": "auto",
            "allow_cpu_fallback": True,
            "torch_installation_directory": str(external_root),
        })
        client = QwenLocalClient(settings)
        _emit(
            "loader_success",
            client_type=type(client).__name__,
            deferred_model_load=True,
        )

        client_module = importlib.import_module(
            "PySubtrans.Transcription.Providers.Clients.QwenLocalClient"
        )
        torch_module = getattr(client_module, "torch")
        qwen_module = importlib.import_module("qwen_asr")
        model_class = getattr(qwen_module, "Qwen3ASRModel", None)
        aligner_class = getattr(qwen_module, "Qwen3ForcedAligner", None)
        transformers_module = importlib.import_module("transformers")
        accelerate_module = importlib.import_module("accelerate")

        modules = [
            _module_evidence("torch", external_root, frozen_root),
            _module_evidence("qwen_asr", external_root, frozen_root),
            _module_evidence("transformers", external_root, frozen_root),
            _module_evidence("accelerate", external_root, frozen_root),
        ]
        _emit(
            "imports_success",
            modules=modules,
            qwen_model_class=bool(model_class),
            qwen_model_factory=bool(model_class and callable(getattr(model_class, "from_pretrained", None))),
            forced_aligner_class=bool(aligner_class),
            forced_aligner_factory=bool(
                aligner_class and callable(getattr(aligner_class, "from_pretrained", None))
            ),
            qwen_supported_language_count=len(getattr(client_module, "_QWEN_SUPPORTED_LANGUAGES", [])),
            transformers_auto_model=hasattr(transformers_module, "AutoModel"),
            accelerate_version=str(getattr(accelerate_module, "__version__", "unknown")),
        )

        origin_by_name = {str(module["name"]): module for module in modules}
        # The packaged build bundles none of the Qwen runtime, so every module must come from the external environment
        origin_validation = {
            f"{name}_external": bool(module["under_external_torch_root"])
            for name, module in origin_by_name.items()
        }
        if bool(getattr(sys, "frozen", False)) and not all(origin_validation.values()):
            raise RuntimeError(f"Frozen origin validation failed: {origin_validation}")
        _emit("origin_validation", **origin_validation)

        cuda_available, cuda_error = _availability(
            getattr(getattr(torch_module, "cuda", None), "is_available", None)
        )
        mps_available, mps_error = _availability(
            getattr(getattr(torch_module, "backends", None), "mps", None)
            and getattr(getattr(torch_module.backends, "mps", None), "is_available", None)
        )
        xpu_available, xpu_error = _availability(
            getattr(getattr(torch_module, "xpu", None), "is_available", None)
        )

        _emit(
            "torch_runtime",
            torch_version=str(getattr(torch_module, "__version__", "unknown")),
            torch_file=str(getattr(torch_module, "__file__", "")),
            cuda_available=cuda_available,
            cuda_error=cuda_error,
            cuda_version=str(getattr(getattr(torch_module, "version", None), "cuda", None)),
            mps_available=mps_available,
            mps_error=mps_error,
            xpu_available=xpu_available,
            xpu_error=xpu_error,
        )
        _emit(
            "inference_boundary",
            model_download_attempted=False,
            inference_attempted=False,
            conclusion="imports_and_class_access_only; no model weights or audio inference",
        )
        return 0
    except Exception as error:
        _emit(
            "failure",
            error_type=type(error).__name__,
            error=str(error),
            traceback=traceback.format_exc(),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
