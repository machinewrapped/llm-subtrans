"""Install the Qwen runtime into the current environment for a source install.

Installs the same runtime that Set up Torch installs for packaged builds.
qwen-asr goes in without its dependencies, then the dependencies it declares are installed, minus those only its demo apps use.
Run after Torch is installed, so the dependencies do not pull in a generic Torch build.
"""

import importlib
import subprocess
import sys

from PySubtrans.Transcription.Torch.QwenRuntime import QWEN_ASR_REQUIREMENT, ReadQwenAsrDependencies


def main() -> int:
    """Install qwen-asr, then its runtime dependencies, stopping at the first failure."""
    result = subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps', QWEN_ASR_REQUIREMENT])
    if result.returncode != 0:
        return result.returncode

    # qwen-asr was installed after this process started, so its metadata is not cached yet
    importlib.invalidate_caches()
    dependencies = ReadQwenAsrDependencies(sys.path)
    if dependencies is None:
        print("qwen-asr was installed but its package metadata could not be found.")
        return 1

    # pip would report the demo app packages left out as missing dependencies of qwen-asr, which reads as a failed install
    result = subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-warn-conflicts', *dependencies])
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
