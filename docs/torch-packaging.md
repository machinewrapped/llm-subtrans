# Torch / Qwen Packaging Reference

Packaged builds bundle Qwen ASR and its supporting Python libraries but exclude `torch`, `torchgen`, and Torch native payloads. A compatible Torch installation is provided externally and loaded in-process before Qwen's lazy import. The external installation must match the frozen application's Python ABI, operating system, and architecture; changing it after Torch has been imported requires an application restart. The distribution does not bundle `ffmpeg` or `ffprobe`; those remain external executables resolved from PATH or the configured ffmpeg path.

Distribution scripts install/check Torch before the Qwen extra and link to the official PyTorch installation selector rather than maintaining hardware-specific wheel recipes. Dependency-audit checks remain a release gate, including findings from bundled Transformers and Accelerate.

After PyInstaller completes, the distro scripts run `scripts/prepare_external_torch.py --metadata-only`, writing `frozen-python-compatibility.json` into the frozen application's `_internal/assets/` directory (PyInstaller 6+ layout). At runtime, the metadata is located via `GetResourcePath("assets", METADATA_FILENAME)`, which resolves through `sys._MEIPASS` in frozen builds and `./assets/` in development. The helper's `--prepare-external-dir` and `--validate-external-dir` modes operate on a complete user-managed venv/site-packages location; they never reconstruct package or native dependency files. Users selecting a hardware build should use the official PyTorch selector.

Both external setup modes require `--frozen-metadata` pointing to the frozen application's JSON. Schema version 1 uses `compatibility` fields `python_implementation`, `python_abi`, `python_version` (major.minor), `os`, `architecture`, and `pointer_bits`. The helper compares the external interpreter's facts to those fields using a 15-second `-I -S` subprocess probe, bypassing site initialization and `.pth` execution. Venv roots resolve Windows `Lib/site-packages` and POSIX `lib/pythonX.Y/site-packages`; a root containing `torch` or a `site-packages` child is also recognized. The validation command requires a venv interpreter and checks directory presence and compatibility, not Torch import or native dependency readiness. PyInstaller failure stops every distro script before metadata generation.

## Torch Subpackage (`PySubtrans/Transcription/Torch/`)

Four modules that handle external Torch installations live in their own subpackage. None import Torch or Qt — only stdlib and `PySubtrans.Helpers`.

| Module | Responsibility |
|--------|----------------|
| `Hardware.py` | GPU detection (NVIDIA/AMD/Intel/Apple Silicon), CUDA driver version matching, PyTorch index URL selection |
| `Validation.py` | ABI compatibility metadata — stamping, reading, comparing and checking frozen-build compatibility |
| `Discovery.py` | Locates existing Torch installations and candidate Python interpreters, preferring one matching the expected compatibility |
| `Runtime.py` | Loads an external Torch venv at runtime (`sys.path` + DLL registration), validates compatibility first |

Consumers:

| Consumer | Imports from |
|----------|-------------|
| `TorchSetupDialog.py` (GUI wizard) | `Hardware` (detection, index URLs), `Validation` (ABI checking), `Discovery` (interpreter and existing-install discovery) |
| `prepare_external_torch.py` (build tool) | `Validation` (metadata stamping and venv probing) |
| `install_torch.py` (installer) | `Hardware` (detection for pre-install torch variant selection) |
| `Provider_QwenLocal.py` / `QwenLocalClient.py` | `Runtime` (config option sentinel, runtime loader) |
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
