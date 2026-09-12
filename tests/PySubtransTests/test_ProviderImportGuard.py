import importlib
import sys
from types import ModuleType
from unittest.mock import patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import skip_if_debugger_attached
from tests.ProviderImportGuard import InstallProviderImportGuard, ProviderImportGuard


class TestProviderImportGuard(LoggedTestCase):
    """Provider isolation must reject imports instead of converting them into skips."""

    @skip_if_debugger_attached
    def test_concrete_provider_imports_fail(self) -> None:
        """Both provider namespaces fail through Python's actual import machinery."""
        guard = ProviderImportGuard()
        with patch.object(sys, 'meta_path', [guard, *sys.meta_path]):
            for package in guard.PACKAGES:
                with self.subTest(package=package):
                    with self.assertRaises(RuntimeError) as context:
                        importlib.import_module(package)
                    self.assertLoggedIn('actionable error', 'tests/integration_tests.py', str(context.exception))
                    self.assertLoggedNotIn('provider not loaded', package, sys.modules)

    @skip_if_debugger_attached
    def test_already_loaded_provider_rejected(self) -> None:
        """Cached modules must not bypass isolation when the runner starts."""
        name = 'PySubtrans.Providers'
        with patch.dict(sys.modules, {name: ModuleType(name)}):
            with self.assertRaises(RuntimeError):
                InstallProviderImportGuard()

    def test_core_provider_interfaces_allowed(self) -> None:
        """Core interfaces and test doubles remain importable."""
        guard = ProviderImportGuard()
        for name in ('PySubtrans.TranslationProvider', 'PySubtrans.Transcription.TranscriptionProvider',
                     'PySubtrans.Helpers.TestCases'):
            self.assertLoggedEqual('core module allowed', None, guard.find_spec(name))
