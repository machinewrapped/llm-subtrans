"""Reject concrete provider dependencies in the fast test process."""
import sys
from collections.abc import Sequence
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec
from types import ModuleType


class ProviderImportGuard(MetaPathFinder):
    """Fail explicitly instead of silently skipping a provider-dependent unit test."""

    PACKAGES : tuple[str, ...] = ('PySubtrans.Providers', 'PySubtrans.Transcription.Providers')

    @classmethod
    def CheckModule(cls, fullname : str) -> None:
        if any(fullname == package or fullname.startswith(package + '.') for package in cls.PACKAGES):
            raise RuntimeError(f'Concrete provider import in unit tests: {fullname}. '
                               'Move this check to tests/IntegrationTests and run tests/integration_tests.py.')

    def find_spec(self, fullname : str, path : Sequence[str]|None = None,
                  target : ModuleType|None = None) -> ModuleSpec|None:
        self.CheckModule(fullname)
        return None


def InstallProviderImportGuard() -> None:
    """Guard the unit-test process, including providers already cached before discovery."""
    for name in tuple(sys.modules):
        ProviderImportGuard.CheckModule(name)
    if not any(isinstance(finder, ProviderImportGuard) for finder in sys.meta_path):
        sys.meta_path.insert(0, ProviderImportGuard())
