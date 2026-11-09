"""Install Torch and the MOSS runtime into a dedicated source-install venv.

Run with envsubtrans's Python: scripts/install_moss_runtime.py <directory>.
Only the venv bootstrap, runtime probe and pip operations use other interpreters.
Exit codes: 0 for GPU support, 1 for CPU only, 2 for installation failure.
"""

import logging
import subprocess
import sys
from argparse import ArgumentParser
from pathlib import Path

from PySubtrans.Helpers.Localization import _
from PySubtrans.Transcription.Torch.MossRuntime import MossDependencyPipArguments, MossPipArguments
from scripts.install_torch import InstallTorch, PrepareEnvironment


def InstallMossRuntime(directory : Path) -> int:
    """Prepare an environment, install Torch first, then MOSS and its dependencies."""
    try:
        python = PrepareEnvironment(directory)
        if python is None:
            return 2

        torch_exit = InstallTorch(python)
        if torch_exit == 2:
            logging.warning(_('Warning: torch installation encountered an error.'))
            return 2

        result = subprocess.run([python, '-m', 'pip', *MossPipArguments()])
        if result.returncode != 0:
            logging.error(_('Failed to install the MOSS package.'))
            return 2

        result = subprocess.run([python, '-m', 'pip', *MossDependencyPipArguments()])
        if result.returncode != 0:
            logging.error(_('Failed to install MOSS runtime dependencies.'))
            return 2

        return torch_exit
    except (OSError, subprocess.SubprocessError) as error:
        logging.error(_('MOSS runtime installation failed: {}').format(error))
        return 2


def main() -> int:
    """Install a MOSS environment at the directory supplied."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='Directory for the MOSS runtime virtual environment')
    args = parser.parse_args()
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(message)s')
    return InstallMossRuntime(args.directory.expanduser().absolute())


if __name__ == '__main__':
    sys.exit(main())
