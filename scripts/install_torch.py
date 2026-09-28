"""Detect GPU hardware and install the correct torch variant.

Called by install.bat / install.sh after base dependencies are installed, but BEFORE ``install_qwen_runtime.py``.
Detects the available GPU hardware and installs torch from the appropriate index URL.
The Qwen runtime's dependencies then find a GPU-capable torch already installed, rather than pulling in a generic build.

Exit codes:
    0 = GPU torch installed (or already present)
    1 = no GPU available; CPU torch installed (or already present)
    2 = error during detection or installation
"""

import logging
import subprocess
import sys

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(message)s')


def _torch_has_gpu() -> bool:
    """Return True if torch is already installed with a GPU backend."""
    try:
        import torch
        backends = [
            torch.cuda,
            getattr(torch.backends, 'mps', None),
            getattr(torch, 'xpu', None),
        ]
        return any(getattr(b, 'is_available', lambda: False)() for b in backends if b)
    except ImportError:
        return False


def main() -> int:
    """Detect hardware and install the correct torch variant."""
    if _torch_has_gpu():
        logging.info("Torch already has a GPU backend -- no action needed.")
        return 0

    from PySubtrans.Transcription.Torch.Hardware import DetectHardware

    detection = DetectHardware()

    if detection is None or not detection.is_gpu or not detection.index_url:
        if detection and detection.guidance:
            logging.info(detection.guidance)
        logging.info("No GPU-accelerated torch variant detected -- installing CPU torch.")
        cmd = [sys.executable, '-m', 'pip', 'install', 'torch']
        result = subprocess.run(cmd)
        return 1 if result.returncode == 0 else 2

    logging.info(detection.description)
    logging.info("Installing GPU-accelerated torch...")

    cmd = [
        sys.executable, '-m', 'pip', 'install',
        'torch', '--extra-index-url', detection.index_url,
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        logging.error("Failed to install torch.")
        return 2

    logging.info("Torch installed successfully.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
