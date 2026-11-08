"""Install Torch and the Qwen runtime into a dedicated source-install venv.

Run with envsubtrans's Python: scripts/install_qwen_runtime.py <directory>.
Only the venv bootstrap, runtime probe and pip operations use other interpreters.
Exit codes: 0 for GPU support, 1 for CPU only, 2 for installation failure.
"""

import logging
import subprocess
import sys
from argparse import ArgumentParser
from pathlib import Path

from PySubtrans.Helpers.Localization import _
from PySubtrans.Transcription.Torch.QwenRuntime import QwenAsrPipArguments, QwenDependencyPipArguments
from PySubtrans.Transcription.Torch.Validation import FindTorchSitePackages
from scripts.install_torch import InstallTorch, PrepareEnvironment


def InstallQwenRuntime(directory : Path) -> int:
    """Prepare an environment, install Torch first, then Qwen and its dependencies."""
    try:
        python = PrepareEnvironment(directory)
        if python is None:
            return 2

        torch_exit = InstallTorch(python)
        if torch_exit == 2:
            logging.warning(_('Warning: torch installation encountered an error.'))
            return 2

        result = subprocess.run([python, '-m', 'pip', *QwenAsrPipArguments()])
        if result.returncode != 0:
            logging.error(_('Failed to install qwen-asr.'))
            return 2

        # Qwen was installed outside this process, so read the target's metadata explicitly.
        # Its pinned dependencies must not come from envsubtrans's sys.path.
        site_packages = FindTorchSitePackages(directory)
        arguments = QwenDependencyPipArguments([str(site_packages)]) if site_packages is not None else None
        if arguments is None:
            logging.error(_('qwen-asr was installed but its package metadata could not be found.'))
            return 2

        result = subprocess.run([python, '-m', 'pip', *arguments])
        if result.returncode != 0:
            logging.error(_('Failed to install Qwen runtime dependencies.'))
            return 2

        return torch_exit
    except (OSError, subprocess.SubprocessError) as error:
        logging.error(_('Qwen runtime installation failed: {}').format(error))
        return 2


def main() -> int:
    """Install a Qwen environment at the directory supplied by the source installer."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='Directory for the Qwen runtime virtual environment')
    args = parser.parse_args()
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(message)s')
    return InstallQwenRuntime(args.directory.expanduser().absolute())


if __name__ == '__main__':
    sys.exit(main())
