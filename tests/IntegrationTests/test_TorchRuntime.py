import json
import platform
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Transcription.Torch import Runtime as TorchRuntime


class TestTorchRuntime(LoggedTestCase):
    """Tests external Torch path validation without importing Torch."""

    def setUp(self):
        super().setUp()
        self._saved_path = TorchRuntime._configured_path
        self._saved_sys_path = list(sys.path)
        TorchRuntime._configured_path = None
        # These tests exercise path validation without a loaded torch runtime.
        # Hide any ambient torch import (present when running in the dev venv)
        # so the "already-loaded" guard in PrepareTorchRuntime does not fire.
        self._torch_patcher = patch.dict(sys.modules, {'torch': None})
        self._torch_patcher.start()

    def tearDown(self):
        self._torch_patcher.stop()
        TorchRuntime._configured_path = self._saved_path
        sys.path[:] = self._saved_sys_path
        super().tearDown()

    def test_empty_path_leaves_import_path_unchanged(self):
        """An empty setting keeps the current environment untouched."""
        original = list(sys.path)
        TorchRuntime.PrepareTorchRuntime('')
        self.assertLoggedEqual('empty path preserves sys.path', original, sys.path)

    def test_external_torch_path_does_not_require_qwen_package(self):
        """Qwen may remain bundled while only Torch is supplied externally."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'torch' / 'lib').mkdir(parents=True)
            with patch.object(TorchRuntime.PathFinder, 'find_spec', return_value=object()):
                TorchRuntime.PrepareTorchRuntime(directory)

            self.assertLoggedIn('external path appended', str(root.resolve()), sys.path)

    def test_path_scoped_lookup_finds_target_without_ambient_torch_spec(self):
        """An external Torch package is found via path-scoped PathFinder even when ambient lookup would miss it."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'torch' / 'lib').mkdir(parents=True)
            (root / 'torch' / '__init__.py').write_text('', encoding='utf-8')

            TorchRuntime.PrepareTorchRuntime(directory)

            self.assertLoggedIn('target package path appended', str(root.resolve()), sys.path)

    def test_invalid_path_has_actionable_error(self):
        """A missing or incomplete installation reports the expected layout."""
        with self.assertRaises(TorchRuntime.TorchRuntimeError) as context:
            TorchRuntime.PrepareTorchRuntime('does-not-exist')
        self.assertIn('site-packages', str(context.exception))

    def test_frozen_metadata_rejects_incompatible_architecture(self):
        """A frozen build refuses an external runtime for another architecture."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'torch' / 'lib').mkdir(parents=True)
            version = sys.version_info
            metadata = {
                'kind': 'llm-subtrans-frozen-python-compatibility',
                'schema_version': 1,
                'compatibility': {
                    'python_implementation': sys.implementation.name,
                    'python_abi': sys.implementation.cache_tag,
                    'python_version': f'{version.major}.{version.minor}',
                    'os': platform.system(),
                    'architecture': 'not-this-machine',
                    'pointer_bits': struct.calcsize('P') * 8,
                },
            }
            metadata_path = root / TorchRuntime.METADATA_FILENAME
            metadata_path.write_text(json.dumps(metadata), encoding='utf-8')

            with patch('PySubtrans.Transcription.Torch.Runtime.FindCompatibilityMetadata', return_value=metadata_path):
                with self.assertRaises(TorchRuntime.TorchRuntimeError) as context:
                    with patch.object(TorchRuntime.PathFinder, 'find_spec', return_value=object()):
                        TorchRuntime.PrepareTorchRuntime(directory)

            self.assertIn('architecture', str(context.exception))

    def test_clearing_configured_runtime_requires_restart(self):
        """Clearing a selected runtime cannot silently retain its import path."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'torch' / 'lib').mkdir(parents=True)
            with patch.object(TorchRuntime.PathFinder, 'find_spec', return_value=object()):
                TorchRuntime.PrepareTorchRuntime(directory)

            with self.assertRaises(TorchRuntime.TorchRuntimeError) as context:
                TorchRuntime.PrepareTorchRuntime('')

            self.assertIn('Restart', str(context.exception))


if __name__ == '__main__':
    unittest.main()
