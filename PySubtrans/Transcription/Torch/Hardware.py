"""GPU hardware detection for PyTorch variant selection.

Pure detection logic -- no Qt, no localization, no Torch imports.
Used by TorchSetupDialog (GUI), install_torch.py (installer), and
any other consumer that needs to choose a PyTorch build variant.
"""

import platform
import shutil
import subprocess
import sys

import regex


# Minimum NVIDIA driver versions per CUDA toolkit.
# Source: https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/
CUDA_MIN_DRIVER_WINDOWS : list[tuple[str, str, str]] = [
    ('13.0', '580.65', 'https://download.pytorch.org/whl/cu130'),
    ('12.6', '560.70', 'https://download.pytorch.org/whl/cu126'),
    ('12.4', '551.61', 'https://download.pytorch.org/whl/cu124'),
    ('12.1', '527.41', 'https://download.pytorch.org/whl/cu121'),
    ('11.8', '520.06', 'https://download.pytorch.org/whl/cu118'),
]

CUDA_MIN_DRIVER_LINUX : list[tuple[str, str, str]] = [
    ('13.0', '580.65.06', 'https://download.pytorch.org/whl/cu130'),
    ('12.6', '560.28.03', 'https://download.pytorch.org/whl/cu126'),
    ('12.4', '550.54.14', 'https://download.pytorch.org/whl/cu124'),
    ('12.1', '525.60.13', 'https://download.pytorch.org/whl/cu121'),
    ('11.8', '520.61.05', 'https://download.pytorch.org/whl/cu118'),
]

ROCM_INDEX_URL = 'https://download.pytorch.org/whl/rocm6.2.4'
CPU_INDEX_URL = 'https://download.pytorch.org/whl/cpu'

_NVIDIA_CUDA_VERSION_PATTERN = regex.compile(
    r'CUDA\s+(?:UMD\s+)?Version:\s*([0-9]+(?:\.[0-9]+)?)',
    regex.IGNORECASE,
)


class HardwareDetection:
    """Result of automatic hardware detection."""

    def __init__(
        self,
        description : str,
        index_url : str,
        is_gpu : bool,
        guidance : str = '',
        hardware_detected : bool = False,
        estimated_size : str = '',
    ):
        self.description = description
        self.index_url = index_url
        self.is_gpu = is_gpu
        self.guidance = guidance
        self.hardware_detected = hardware_detected
        self.estimated_size = estimated_size


def ParseDriverVersion(version_str : str) -> tuple[int, ...]:
    """Parse a dotted driver version string into a comparable tuple."""
    parts : list[int] = []
    for segment in version_str.strip().split('.'):
        try:
            parts.append(int(segment))
        except ValueError:
            break
    return tuple(parts)


def DetectNvidiaDriver() -> str|None:
    """Query the NVIDIA driver version via nvidia-smi, or return None."""
    nvidia_smi = shutil.which('nvidia-smi')
    if not nvidia_smi:
        return None

    try:
        result = subprocess.run(
            [nvidia_smi, '--query-gpu=driver_version', '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Multi-GPU: take the first line
            return result.stdout.strip().splitlines()[0].strip()
    except (OSError, subprocess.TimeoutExpired):
        pass

    return None


def DetectNvidiaCudaVersion() -> str|None:
    """Read the maximum CUDA API version reported by the NVIDIA driver."""
    nvidia_smi = shutil.which('nvidia-smi')
    if not nvidia_smi:
        return None

    try:
        result = subprocess.run(
            [nvidia_smi], capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            match = _NVIDIA_CUDA_VERSION_PATTERN.search(result.stdout)
            if match:
                return match.group(1)
    except (OSError, subprocess.TimeoutExpired):
        pass

    return None


def SelectCudaBuild(
    driver_version : str,
    reported_cuda_version : str|None,
    table : list[tuple[str, str, str]],
) -> tuple[str, str]|None:
    """Select the newest available PyTorch build supported by the driver."""
    driver_tuple = ParseDriverVersion(driver_version)
    reported_cuda_tuple = ParseDriverVersion(reported_cuda_version) if reported_cuda_version else None

    for cuda_version, min_driver, index_url in table:
        if driver_tuple < ParseDriverVersion(min_driver):
            continue
        if reported_cuda_tuple is not None and ParseDriverVersion(cuda_version) > reported_cuda_tuple:
            continue
        return cuda_version, index_url

    return None


def DetectGpuHardware() -> str|None:
    """Scan for GPU hardware by vendor name, without relying on driver toolkits.

    Returns 'nvidia', 'amd', 'intel', or None.
    """
    gpu_names : list[str] = []

    if sys.platform == 'win32':
        try:
            result = subprocess.run(
                ['wmic', 'path', 'win32_VideoController', 'get', 'Name'],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                gpu_names = result.stdout.strip().splitlines()
        except (OSError, subprocess.TimeoutExpired):
            pass

    elif sys.platform == 'linux':
        lspci = shutil.which('lspci')
        if lspci:
            try:
                result = subprocess.run(
                    [lspci], capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    gpu_names = [
                        line for line in result.stdout.splitlines()
                        if any(tag in line.lower() for tag in ('vga', '3d', 'display'))
                    ]
            except (OSError, subprocess.TimeoutExpired):
                pass

    combined = ' '.join(gpu_names).lower()
    if 'nvidia' in combined or 'geforce' in combined or 'quadro' in combined or 'tesla' in combined:
        return 'nvidia'
    if 'amd' in combined or 'radeon' in combined:
        return 'amd'
    if 'intel' in combined and ('arc' in combined or 'iris' in combined or 'xe' in combined):
        return 'intel'

    return None


def DetectHardware() -> HardwareDetection|None:
    """Detect the best available hardware for Torch and return install parameters.

    Returns None when no GPU is detected at all (caller decides what to do).
    """
    # macOS Apple Silicon: MPS is in the default PyPI torch wheel
    if sys.platform == 'darwin' and platform.machine() == 'arm64':
        return HardwareDetection(
            description="Apple Silicon detected -- Torch will use Metal Performance Shaders (MPS)",
            index_url='',  # default PyPI wheel includes MPS
            is_gpu=True,
        )

    # Try NVIDIA via driver query
    driver_version = DetectNvidiaDriver()
    if driver_version:
        table = CUDA_MIN_DRIVER_LINUX if sys.platform == 'linux' else CUDA_MIN_DRIVER_WINDOWS
        reported_cuda_version = DetectNvidiaCudaVersion()
        selected_build = SelectCudaBuild(driver_version, reported_cuda_version, table)

        if selected_build:
            cuda_version, index_url = selected_build
            reported_text = f"; CUDA {reported_cuda_version}" if reported_cuda_version else ""
            return HardwareDetection(
                description=f"NVIDIA GPU detected (driver {driver_version}{reported_text}) -- selecting CUDA {cuda_version}",
                index_url=index_url,
                is_gpu=True,
            )

        # Driver found but too old for any known CUDA
        return HardwareDetection(
            description=f"NVIDIA GPU detected but driver {driver_version} is too old for CUDA",
            index_url=CPU_INDEX_URL,
            is_gpu=False,
            guidance="Update your driver from nvidia.com for GPU acceleration.",
            hardware_detected=True,
        )

    # Try AMD ROCm (Linux only — PyTorch does not ship ROCm wheels for Windows)
    if sys.platform == 'linux' and shutil.which('rocminfo'):
        return HardwareDetection(
            description="AMD GPU detected (ROCm) -- will install Torch with ROCm support",
            index_url=ROCM_INDEX_URL,
            is_gpu=True,
        )

    # No NVIDIA driver detected — scan for GPU hardware and give specific guidance
    gpu_vendor = DetectGpuHardware()

    if gpu_vendor == 'nvidia':
        return HardwareDetection(
            description="NVIDIA GPU detected, but its driver is unavailable",
            index_url=CPU_INDEX_URL,
            is_gpu=False,
            guidance="Install the latest NVIDIA driver from nvidia.com, restart, and try again.",
            hardware_detected=True,
        )

    if gpu_vendor == 'amd':
        if sys.platform == 'linux':
            return HardwareDetection(
                description="AMD GPU found but ROCm is not installed",
                index_url=CPU_INDEX_URL,
                is_gpu=False,
                guidance="Install ROCm from AMD's documentation, restart, and try again.",
                hardware_detected=True,
            )
        return HardwareDetection(
            description="AMD GPU found",
            index_url=CPU_INDEX_URL,
            is_gpu=False,
            guidance="PyTorch GPU support for AMD requires Linux with ROCm.",
            hardware_detected=True,
        )

    if gpu_vendor == 'intel':
        return HardwareDetection(
            description="Intel GPU found",
            index_url=CPU_INDEX_URL,
            is_gpu=False,
            guidance="PyTorch XPU support requires the Intel oneAPI toolkit (intel.com/oneapi).",
            hardware_detected=True,
        )

    return None
