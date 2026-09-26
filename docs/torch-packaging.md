# Torch / Qwen Packaging Reference

Packaged builds bundle neither Torch nor the Qwen runtime (qwen-asr, Transformers, Accelerate, librosa, nagisa, soynlp and their dependencies). Both are installed into an external, user-managed venv and loaded in-process: the venv's site-packages is appended to `sys.path` before Qwen's lazy import, so bundled modules take precedence over the venv's copies. The external installation must match the frozen application's Python ABI, operating system, and architecture; changing it after Torch has been imported requires an application restart. The distribution does not bundle `ffmpeg` or `ffprobe`; those remain external executables resolved from PATH or the configured ffmpeg path.

The venv contributes site-packages but not a standard library, so `hooks/hook-PySubtrans.py` bundles the whole standard library apart from Tk, IDLE and CPython's tests. The distro scripts exclude `numpy` and the packages built on it (`scipy`, `numba`, `llvmlite`, `pandas`, `PIL`): openai and pygments import them optionally, and a bundled numpy would shadow the one the venv's scipy and numba were built against.

Local transcription setup (the Torch setup wizard) installs the Qwen runtime after Torch, and `scripts/install_qwen_runtime.py` does the same for source installs. qwen-asr is installed with `--no-deps` at the version `QwenRuntime.py` pins, then the dependencies its metadata declares are installed as declared, minus those only its demo apps use (gradio, flask, sox, qwen-omni-utils, pytz). Bumping qwen-asr's pin brings its dependency pins with it. Environments set up by 1.7.0 contain Torch alone; the provider reports the missing runtime, and selecting the environment in the setup wizard offers to install it there.

Distribution scripts do not install Torch or qwen-asr into the build environment. Dependency-audit checks remain a release gate for the bundled packages.

After PyInstaller completes, the distro scripts run `scripts/prepare_external_torch.py --metadata-only`, writing `frozen-python-compatibility.json` into the frozen application's `_internal/assets/` directory (PyInstaller 6+ layout). At runtime, the metadata is located via `GetResourcePath("assets", METADATA_FILENAME)`, which resolves through `sys._MEIPASS` in frozen builds and `./assets/` in development. The helper's `--prepare-external-dir` and `--validate-external-dir` modes operate on a complete user-managed venv/site-packages location; they never reconstruct package or native dependency files. Users selecting a hardware build should use the official PyTorch selector.

Both external setup modes require `--frozen-metadata` pointing to the frozen application's JSON. Schema version 1 uses `compatibility` fields `python_implementation`, `python_abi`, `python_version` (major.minor), `os`, `architecture`, and `pointer_bits`. The helper compares the external interpreter's facts to those fields using a 15-second `-I -S` subprocess probe, bypassing site initialization and `.pth` execution. Venv roots resolve Windows `Lib/site-packages` and POSIX `lib/pythonX.Y/site-packages`; a root containing `torch` or a `site-packages` child is also recognized. The validation command requires a venv interpreter and checks directory presence and compatibility, not Torch import or native dependency readiness. PyInstaller failure stops every distro script before metadata generation.

## Torch Subpackage (`PySubtrans/Transcription/Torch/`)

Five modules that handle external Torch installations live in their own subpackage. None import Torch or Qt — only stdlib and `PySubtrans.Helpers`.

| Module | Responsibility |
|--------|----------------|
| `Hardware.py` | GPU detection (NVIDIA/AMD/Intel/Apple Silicon), CUDA driver version matching, PyTorch index URL selection |
| `Validation.py` | ABI compatibility metadata — stamping, reading, comparing and checking frozen-build compatibility |
| `Discovery.py` | Locates existing Torch installations and candidate Python interpreters, preferring one matching the expected compatibility |
| `Runtime.py` | Loads an external Torch venv at runtime (`sys.path` + DLL registration), validates compatibility first |
| `QwenRuntime.py` | Pins qwen-asr, lists the dependencies to install with it, and checks whether a Torch venv contains the Qwen runtime |

Consumers:

| Consumer | Imports from |
|----------|-------------|
| `TorchSetupDialog.py` (GUI wizard) | `Hardware` (detection, index URLs), `Validation` (ABI checking), `Discovery` (interpreter and existing-install discovery), `QwenRuntime` (requirements and runtime checks) |
| `prepare_external_torch.py` (build tool) | `Validation` (metadata stamping and venv probing) |
| `install_torch.py` (installer) | `Hardware` (detection for pre-install torch variant selection) |
| `Provider_QwenLocal.py` / `QwenLocalClient.py` | `Runtime` (config option sentinel, runtime loader), `QwenRuntime` (missing-runtime checks) |
| `SettingsDialog.py` | `Runtime` (`TorchConfigOption` sentinel) |

Key `Validation` functions:
- **`normalise_architecture()`** — merged alias table covering both x86 and ARM variants
- **`candidate_site_packages_paths()` / `find_torch_site_packages()`** — canonical site-packages resolution for all layout variants
- **`build_current_compatibility()`** — builds the 6-field compatibility dict from the running interpreter
- **`find_compatibility_metadata()`** — locates the metadata file via `GetResourcePath`
- **`read_compatibility_metadata()` / `check_compatibility()` / `compare_compatibility()`** — reads and validates metadata, with an `error_type` parameter so each consumer raises its own exception type; `compare_compatibility()` returns the mismatches so the GUI wizard can warn without blocking

Key `Hardware` functions:
- **`DetectHardware()`** — main entry point: returns a `HardwareDetection` with description, index URL, and GPU flag
- **`SelectCudaBuild()`** — matches a driver version against the CUDA toolkit table
- **`DetectNvidiaDriver()` / `DetectNvidiaCudaVersion()`** — nvidia-smi queries
- **`DetectGpuHardware()`** — vendor scan via wmic/lspci when no driver toolkit is available
