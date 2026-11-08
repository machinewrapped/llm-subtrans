"""Detect hardware and install Torch using a selected environment's interpreter.

The Qwen source installer reuses InstallTorch after preparing its own venv.
Running this script directly targets the current interpreter.

Exit codes: 0 for GPU support, 1 for CPU only, 2 for installation failure.
"""

import logging
import subprocess
import sys
from pathlib import Path

from PySubtrans.Helpers.Localization import _
from PySubtrans.Transcription.Torch.Discovery import FindEnvironmentPython, PythonMeetsMinimum
from PySubtrans.Transcription.Torch.Hardware import DetectHardware


_GPU_PROBE = '''
import importlib
import sys

try:
    torch = importlib.import_module('torch')
except (ImportError, OSError):
    sys.exit(1)

backends = [torch.cuda, getattr(torch.backends, 'mps', None), getattr(torch, 'xpu', None)]
available = any(getattr(backend, 'is_available', lambda: False)() for backend in backends if backend)
sys.exit(0 if available else 2)
'''

# Exit codes from the probe
_PROBE_GPU = 0
_PROBE_NO_TORCH = 1
_PROBE_CPU_TORCH = 2


def PrepareEnvironment(directory : Path) -> str|None:
    """Create a runtime venv when needed and accept any Python at least 3.10.

    Runtime installers share this bootstrap without depending on the app's ABI.
    Every package operation later uses the returned interpreter.
    """
    python = FindEnvironmentPython(directory)
    if python is None:
        if not PythonMeetsMinimum(sys.executable):
            logging.error(_('Python 3.10 or later is required to create a local runtime environment.'))
            return None

        result = subprocess.run([sys.executable, '-m', 'venv', str(directory)])
        if result.returncode != 0:
            logging.error(_('Failed to create the local runtime environment.'))
            return None

        python = FindEnvironmentPython(directory)

    if python is None or not PythonMeetsMinimum(python):
        logging.error(_('The local runtime environment needs a working Python 3.10 or later.'))
        return None

    return python


def InstallTorch(python : str) -> int:
    """Install the hardware-appropriate Torch build into the target environment."""
    try:
        # Probe the target, because the app environment must not import or supply Torch.
        probe = subprocess.run([python, '-I', '-c', _GPU_PROBE], capture_output=True, text=True, timeout=30)
        if probe.returncode == _PROBE_GPU:
            logging.info('Torch already has a GPU backend -- no action needed.')
            return 0

        detection = DetectHardware()
        is_gpu = detection is not None and detection.is_gpu
        command = [python, '-m', 'pip', 'install', 'torch']

        if detection is not None:
            logging.info(detection.description)
            if detection.guidance:
                logging.info(detection.guidance)

        if is_gpu:
            logging.info('Installing GPU-accelerated torch...')

            # pip treats an installed CPU build as satisfying "torch", so remove it first
            if probe.returncode == _PROBE_CPU_TORCH:
                logging.info('Replacing the installed CPU-only torch build...')
                result = subprocess.run([python, '-m', 'pip', 'uninstall', '-y', 'torch'])
                if result.returncode != 0:
                    logging.error(_('Failed to remove the CPU-only torch build.'))
                    return 2

            # Use the build's index only: with an extra index, pip picks the highest version anywhere,
            # and a newer CPU-only wheel on PyPI would win over the GPU build.
            # Apple Silicon uses the default wheel, which includes MPS, so it has no index.
            if detection is not None and detection.index_url:
                command.extend(['--index-url', detection.index_url])
        else:
            logging.info('No GPU-accelerated torch variant detected -- installing CPU torch.')

        result = subprocess.run(command)
        if result.returncode != 0:
            logging.error(_('Failed to install torch.'))
            return 2

        logging.info('Torch installed successfully.')
        return 0 if is_gpu else 1
    except (OSError, subprocess.SubprocessError) as error:
        logging.error(_('Torch installation failed: {}').format(error))
        return 2


def main() -> int:
    """Preserve the standalone installer entry point for the current interpreter."""
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(message)s')
    return InstallTorch(sys.executable)


if __name__ == '__main__':
    sys.exit(main())
