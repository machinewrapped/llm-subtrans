# Torch / Qwen Packaging Reference

Packaged builds bundle neither Torch nor the local transcription runtimes. Qwen Local and MOSS Local install their model packages and dependencies into separate, user-managed virtual environments. `WorkerHost` starts the selected worker with that environment's own Python, so Torch and the runtime are imported only in the worker process. The application process does not append the external environment to `sys.path`, register its DLL directories, or load Torch.

The distribution does not bundle `ffmpeg` or `ffprobe`; those remain external executables resolved from PATH or the configured ffmpeg path.

The PyInstaller hook keeps the worker scripts as data files because the workers are launched by path. It collects provider and format submodules for the application process and excludes Torch packages from the bundle. The hook does not bundle an external environment's standard library: workers use the standard library belonging to the Python executable that starts them.

## Source runtime environments

Run the Qwen installer using `envsubtrans`'s Python, for example `./envsubtrans/Scripts/python.exe scripts/install_qwen_runtime.py envqwen` on Windows or `./envsubtrans/bin/python scripts/install_qwen_runtime.py envqwen` on Linux/macOS. `install.bat` and `install.sh` use this command when Qwen Local is selected for local transcription. The app's environment stays free of Torch and Transformers; the standalone Qwen worker uses `envqwen`'s interpreter. MOSS Local has its own environment, `envmoss`, installed by `scripts/install_moss_runtime.py`, because it needs Transformers 5 while qwen-asr pins Transformers 4.

An existing target interpreter can be any Python 3.10 or later. When the target has no interpreter, the installer checks the current interpreter with `Discovery.PythonMeetsMinimum` before creating a venv. It reuses `install_torch.InstallTorch` for GPU build selection. Exit codes are 0 for GPU support, 1 for CPU-only success and 2 for failure.

`QwenRuntime.QWEN_ENVIRONMENT_NAME` names the default environment folder, `envqwen`, used by source installs and as the setup wizard's default. In source runs, `Discovery.ResolveEnvironmentPython` prefers that directory under `GetAppDir()` when no setting is supplied. A missing or incomplete default falls back to the current interpreter, preserving older source installs with Qwen in `envsubtrans`. Explicit settings take precedence. Frozen builds require an external environment setting.

## Torch subpackage

The modules under `PySubtrans/Transcription/Torch/` describe and discover external runtimes. None import Torch or Qt.

| Module | Responsibility |
|--------|----------------|
| `Hardware.py` | GPU detection, CUDA driver matching, and PyTorch index URL selection |
| `Validation.py` | Locating Torch site-packages and venv interpreters |
| `Discovery.py` | Locating existing Torch environments and Python interpreters; frozen builds choose the first candidate meeting Python 3.10+ |
| `QwenRuntime.py` | Qwen package requirements and runtime checks |
| `MossRuntime.py` | MOSS package requirements, model revision, and runtime checks |
| `LocalRuntime.py` | Runtime setup options, environment names, pip steps, and runtime checks |

Consumers are split by responsibility:

| Consumer | Imports from |
|----------|--------------|
| `TorchSetupDialog.py` (GUI wizard) | `Hardware`, `Discovery`, `Validation`, and `LocalRuntime` |
| `install_torch.py` and runtime installers | `Hardware`, `Discovery`, `Validation`, and the relevant runtime description |
| `Provider_QwenLocal.py` / `QwenLocalClient.py` | `LocalRuntime`, `QwenRuntime`, and worker-host support |
| `Provider_MossLocal.py` / `MossLocalClient.py` | `LocalRuntime`, `MossRuntime`, and worker-host support |

The setup wizard detects existing environments, permits manual selection, installs Torch and the selected runtime into a new environment, can add a missing runtime to an existing Torch environment, and refuses to install one local runtime into an environment containing the other. Compatibility with the frozen application's Python ABI is not checked because the model code runs under the selected environment's own interpreter.
