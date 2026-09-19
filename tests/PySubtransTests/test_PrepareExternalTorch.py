import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import skip_if_debugger_attached
from PySubtrans.Transcription.Torch.Validation import CompareCompatibility, FindTorchSitePackages
from scripts import prepare_external_torch


class TestPrepareExternalTorch(LoggedTestCase):
    """Tests metadata-only and empty external-location preparation."""

    def test_metadata_describes_current_python_and_external_torch(self):
        """Metadata contains the ABI, operating system, architecture, and external policy."""
        metadata = prepare_external_torch.BuildCompatibilityMetadata()

        self.assertLoggedIn("compatibility metadata", "compatibility", metadata)
        compatibility = metadata["compatibility"]
        self.assertLoggedIn("Python ABI", "python_abi", compatibility)
        self.assertLoggedIn("operating system", "os", compatibility)
        self.assertLoggedIn("architecture", "architecture", compatibility)
        torch_meta = metadata["torch"]
        assert isinstance(torch_meta, dict)
        self.assertLoggedEqual("external Torch policy", "external", torch_meta["installation"])

    def test_prepare_creates_only_layout_and_metadata(self):
        """Preparation never copies a Torch or native payload."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_directory = root / "external-torch"
            frozen_metadata = root / "frozen" / prepare_external_torch.METADATA_FILENAME
            prepare_external_torch.WriteCompatibilityMetadata(frozen_metadata)
            metadata = prepare_external_torch.PrepareExternalTorch(output_directory, frozen_metadata)

            external_site_packages = output_directory / "site-packages"
            self.assertLoggedIsInstance("metadata type", metadata, dict)
            self.assertLoggedTrue("site-packages prepared", external_site_packages.is_dir())
            self.assertLoggedFalse("Torch package not copied", (external_site_packages / "torch").exists())
            self.assertLoggedFalse("Torchgen package not copied", (external_site_packages / "torchgen").exists())
            self.assertLoggedFalse("native payload not copied", (external_site_packages / "torch" / "lib").exists())

            external_json = json.loads((output_directory / prepare_external_torch.METADATA_FILENAME).read_text(encoding="utf-8"))
            frozen_json = json.loads(frozen_metadata.read_text(encoding="utf-8"))
            self.assertLoggedEqual("external metadata", external_json, frozen_json)

    def test_compare_compatibility_reports_differing_fields(self) -> None:
        """Compatibility comparison reports each field that does not match."""
        expected = {
            'python_implementation': 'cpython', 'python_abi': 'cpython-312',
            'python_version': '3.12', 'os': 'Windows', 'architecture': 'AMD64', 'pointer_bits': 64,
        }
        actual = dict(expected)
        actual['python_abi'] = 'cpython-313'
        actual['architecture'] = 'arm64'

        mismatches = CompareCompatibility(actual, expected)

        self.assertLoggedEqual('two fields differ', 2, len(mismatches))
        self.assertLoggedTrue('ABI difference reported', any('python_abi' in mismatch for mismatch in mismatches))
        self.assertLoggedTrue('architecture difference reported', any('architecture' in mismatch for mismatch in mismatches))

    def test_compare_compatibility_accepts_equivalent_architectures(self) -> None:
        """Architecture aliases do not count as a mismatch."""
        expected = {
            'python_implementation': 'cpython', 'python_abi': 'cpython-312',
            'python_version': '3.12', 'os': 'Windows', 'architecture': 'x86_64', 'pointer_bits': 64,
        }
        actual = dict(expected)
        actual['architecture'] = 'AMD64'

        self.assertLoggedEqual('aliases match', [], CompareCompatibility(actual, expected))

    def test_find_torch_site_packages_recognises_other_python_version(self) -> None:
        """A venv built by another Python minor version is still detected."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site_packages = root / 'lib' / 'python3.9' / 'site-packages'
            (site_packages / 'torch').mkdir(parents=True)

            found = FindTorchSitePackages(root)

            self.assertLoggedEqual('versioned POSIX layout detected', site_packages.resolve(), found)

    def test_metadata_only_does_not_create_an_external_torch_payload(self):
        """Build metadata mode never copies Torch back into the frozen deliverable."""
        with tempfile.TemporaryDirectory() as directory:
            build_root = Path(directory) / "dist"
            metadata_path = build_root / "gui-subtrans" / prepare_external_torch.METADATA_FILENAME
            result = prepare_external_torch.main([
                "--metadata-only",
                "--metadata-path",
                str(metadata_path),
            ])

            self.assertLoggedEqual("metadata-only command result", 0, result)
            self.assertLoggedTrue("metadata exists", metadata_path.is_file())
            self.assertLoggedFalse("no Torch payload", (build_root / "gui-subtrans" / "torch").exists())
            self.assertLoggedFalse("no Torch sidecar", (build_root / "torch-runtime").exists())
            self.assertLoggedEqual("only JSON in deliverable", [metadata_path],
                                   [path for path in build_root.rglob('*') if path.is_file()])

    def test_validate_checks_the_external_interpreter_compatibility(self):
        """Validation checks the complete venv's own ABI and platform facts."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "external-torch"
            (root / "Lib" / "site-packages" / "torch").mkdir(parents=True)
            python_executable = root / "Scripts" / "python.exe"
            python_executable.parent.mkdir(parents=True)
            python_executable.write_bytes(b"test interpreter marker")
            expected = prepare_external_torch.BuildCompatibilityMetadata()["compatibility"]
            frozen_metadata = Path(directory) / prepare_external_torch.METADATA_FILENAME
            prepare_external_torch.WriteCompatibilityMetadata(frozen_metadata)

            with patch.object(prepare_external_torch, "ProbeVenvCompatibility", return_value=expected):
                validated = prepare_external_torch.ValidateExternalTorch(root, frozen_metadata)

            self.assertLoggedEqual("validated venv root", root.resolve(), validated)

    @skip_if_debugger_attached
    def test_validation_rejects_frozen_mismatch_even_when_helper_and_venv_match(self) -> None:
        """The frozen JSON, rather than the helper interpreter, defines the target."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Lib" / "site-packages" / "torch").mkdir(parents=True)
            executable = root / "Scripts" / "python.exe"
            executable.parent.mkdir()
            executable.touch()
            metadata = prepare_external_torch.BuildCompatibilityMetadata()
            expected = metadata['compatibility']
            assert isinstance(expected, dict)
            actual = dict(expected)
            expected['python_abi'] = 'incompatible-frozen-abi'
            frozen_metadata = root / prepare_external_torch.METADATA_FILENAME
            frozen_metadata.write_text(json.dumps(metadata), encoding='utf-8')

            with patch.object(prepare_external_torch, 'ProbeVenvCompatibility', return_value=actual):
                with self.assertRaisesRegex(RuntimeError, 'python_abi'):
                    prepare_external_torch.ValidateExternalTorch(root, frozen_metadata)

            output = root / 'new-external'
            with self.assertRaisesRegex(RuntimeError, 'python_abi'):
                prepare_external_torch.PrepareExternalTorch(output, frozen_metadata)
            self.assertLoggedFalse('mismatch creates no external directory', output.exists())

    def test_posix_venv_root_resolves_versioned_site_packages(self) -> None:
        """The helper accepts the POSIX venv root documented for the runtime."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site_packages = root / 'lib' / 'python3.12' / 'site-packages'
            (site_packages / 'torch').mkdir(parents=True)
            executable = root / 'bin' / 'python'
            executable.parent.mkdir()
            executable.touch()
            frozen_metadata = root / prepare_external_torch.METADATA_FILENAME
            metadata = prepare_external_torch.WriteCompatibilityMetadata(frozen_metadata)
            with patch.object(prepare_external_torch, 'ProbeVenvCompatibility', return_value=metadata['compatibility']):
                validated = prepare_external_torch.ValidateExternalTorch(root, frozen_metadata)
            self.assertLoggedEqual('POSIX venv accepted', root.resolve(), validated)
            self.assertLoggedEqual('POSIX layout preserved', site_packages.resolve(),
                                   prepare_external_torch._GetSitePackagesDirectory(root, create=True))

    def test_external_probe_disables_site_and_has_a_deadline(self) -> None:
        """An actual venv's .pth startup code cannot run during the probe."""
        from PySubtrans.Transcription.Torch import Validation as TorchValidation

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'venv'
            venv.EnvBuilder(with_pip=False).create(root)
            executable = prepare_external_torch.FindVenvPython(root)
            assert executable is not None
            if os.name == 'nt':
                site_packages = root / 'Lib' / 'site-packages'
            else:
                site_packages = root / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
            marker = Path(directory) / 'pth-executed'
            (site_packages / 'probe-test.pth').write_text(
                f"import pathlib; pathlib.Path({str(marker)!r}).touch()\n", encoding='utf-8')
            with patch.object(TorchValidation.subprocess, 'run', wraps=subprocess.run) as run:
                actual = prepare_external_torch.ProbeVenvCompatibility(executable)
            self.assertLoggedFalse('external .pth was not executed', marker.exists())
            self.assertLoggedEqual('actual interpreter facts',
                                   prepare_external_torch.BuildCompatibilityMetadata()['compatibility'], actual)
            self.assertLoggedIn('site initialization disabled', '-S', run.call_args.args[0])
            self.assertLoggedEqual('probe timeout seconds', 15, run.call_args.kwargs['timeout'])

    @skip_if_debugger_attached
    def test_external_cli_requires_frozen_metadata(self) -> None:
        """Neither external workflow may infer a frozen target from the helper."""
        for mode in ('--prepare-external-dir', '--validate-external-dir'):
            with self.subTest(mode=mode), self.assertRaises(SystemExit) as error:
                # argparse prints usage + error to stderr before raising SystemExit;
                # redirect so the expected error does not pollute test runner output.
                with contextlib.redirect_stderr(io.StringIO()):
                    prepare_external_torch.main([mode, 'unused'])
            self.assertLoggedEqual('missing target is a CLI error', 2, error.exception.code)

    @skip_if_debugger_attached
    def test_incomplete_frozen_metadata_is_rejected(self) -> None:
        """Missing target fields cannot pass validation as unspecified values."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'invalid.json'
            metadata = prepare_external_torch.BuildCompatibilityMetadata()
            metadata['compatibility'] = {'python_abi': 'cpython-312'}
            path.write_text(json.dumps(metadata), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'missing or invalid'):
                prepare_external_torch.ReadCompatibilityMetadata(path)

    def test_distro_failure_guards_precede_metadata(self) -> None:
        """A failed PyInstaller command cannot be masked by metadata generation."""
        scripts = Path(__file__).resolve().parents[2] / 'scripts'
        for name in ('makedistro.sh', 'makedistro-mac.sh'):
            source = (scripts / name).read_text(encoding='utf-8')
            build_end = source.index('scripts/gui-subtrans.py || exit $?')
            self.assertLoggedLess('shell failure exits before metadata', build_end, source.index('--metadata-only'))
        source = (scripts / 'makedistro.bat').read_text(encoding='utf-8')
        guard = source.split('"scripts/gui-subtrans.py"', 1)[1].split('scripts\\prepare_external_torch.py', 1)[0]
        self.assertLoggedIn('batch failure checked immediately', 'if errorlevel 1 (', guard)
        self.assertLoggedIn('batch preserves failed exit code', 'exit /b %errorlevel%', guard)

        if os.name == 'nt':
            guard = guard[:guard.index('.\\envsubtrans')]
            with tempfile.TemporaryDirectory() as directory:
                script = Path(directory) / 'failed-build.bat'
                script.write_text('@echo off\ncmd /c exit 23\n' + guard + '\necho METADATA_CALLED\n', encoding='utf-8')
                result = subprocess.run(['cmd.exe', '/d', '/c', str(script)], capture_output=True, text=True, timeout=15)
                self.assertLoggedEqual('failed build exit code preserved', 23, result.returncode)
                self.assertLoggedNotIn('metadata never invoked', 'METADATA_CALLED', result.stdout)

    def test_shell_build_failure_preserves_exit_code(self) -> None:
        """Both real shell build command blocks stop before a following metadata call."""
        bash = str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Git' / 'bin' / 'bash.exe') if os.name == 'nt' else shutil.which('bash')
        if not bash or not Path(bash).is_file():
            self.skipTest('Bash is unavailable')
        scripts = Path(__file__).resolve().parents[2] / 'scripts'
        for name in ('makedistro.sh', 'makedistro-mac.sh'):
            source = (scripts / name).read_text(encoding='utf-8')
            start = source.index('\npyinstaller --') if name == 'makedistro.sh' else source.index('\n./envsubtrans/bin/pyinstaller --')
            end = source.index('\n./envsubtrans/bin/python scripts/prepare_external_torch.py', start)
            command = source[start:end].replace('./envsubtrans/bin/pyinstaller', 'pyinstaller')
            fixture = 'pyinstaller() { return 23; }\n' + command + '\necho METADATA_CALLED\n'
            result = subprocess.run([bash, '-c', fixture], capture_output=True, text=True, timeout=15)
            self.assertLoggedEqual(f'{name} preserves failure', 23, result.returncode)
            self.assertLoggedNotIn(f'{name} skips metadata', 'METADATA_CALLED', result.stdout)

    def test_install_torch_recognises_xpu_and_installers_require_cpu_consent(self) -> None:
        """install_torch.py treats XPU as a GPU backend; install scripts show CPU consent text."""
        from scripts import install_torch

        # Simulate torch with an XPU backend available
        mock_torch = SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: False),
            backends=SimpleNamespace(),
            xpu=SimpleNamespace(is_available=lambda: True),
        )
        with patch.dict('sys.modules', {'torch': mock_torch}):
            result = install_torch.main()
        self.assertLoggedEqual("XPU detected exits 0", 0, result)

        # Simulate torch with no GPU backend at all -> falls through to detect_hardware -> CPU install
        mock_torch_cpu = SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: False),
            backends=SimpleNamespace(),
        )
        mock_pip = SimpleNamespace(returncode=0)
        with patch.dict('sys.modules', {'torch': mock_torch_cpu}), \
             patch('PySubtrans.Transcription.Torch.Hardware.DetectHardware', return_value=None), \
             patch('scripts.install_torch.subprocess.run', return_value=mock_pip):
             result = install_torch.main()
        self.assertLoggedEqual("No GPU exits 1", 1, result)

        # Install scripts still carry the CPU consent guidance
        root = Path(__file__).resolve().parents[2]
        for name in ('install.bat', 'install.sh'):
            source = (root / name).read_text(encoding='utf-8')
            self.assertLoggedIn(f'{name} consent guidance', 'CPU inference is disabled by default', source)
            self.assertLoggedIn(f'{name} names persistent setting', 'allow_cpu_fallback', source)


if __name__ == "__main__":
    unittest.main()
