from pathlib import Path
from unittest.mock import patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Transcription.Torch.MossRuntime import (
    MOSS_DEPENDENCIES,
    MOSS_DISTRIBUTION,
    MOSS_REQUIREMENT,
    HasMossRuntime,
    MossDependencyPipArguments,
    MossPipArguments,
)
from PySubtrans.Transcription.Torch.Requirements import RequirementName

_MODULE = 'PySubtrans.Transcription.Torch.MossRuntime'
_SITE_PACKAGES = Path('/moss-env/Lib/site-packages')


class TestMossRuntimePipArguments(LoggedTestCase):
    """The runtime installs in two parts: the package on its own, then the dependencies it needs."""

    def test_package_installed_without_dependencies(self) -> None:
        """The package's own requirements include its web app's, so pip must not resolve them."""
        self.assertLoggedEqual("package arguments", ['install', '--no-deps', MOSS_REQUIREMENT], MossPipArguments())

    def test_dependencies_leave_out_web_app(self) -> None:
        """The web app's server packages are never installed."""
        names = {RequirementName(requirement) for requirement in MossDependencyPipArguments() if not requirement.startswith('-')}

        for web_package in ('fastapi', 'uvicorn', 'python-multipart'):
            self.assertLoggedNotIn(f"{web_package} left out", web_package, names)
        self.assertLoggedIn("transformers installed", 'transformers', names)


class TestMossRuntimeDetection(LoggedTestCase):
    """Environments are checked for the MOSS package and every dependency it needs."""

    def _has_runtime(self, installed : set[str], site_packages : Path|None = _SITE_PACKAGES) -> bool:
        """Check an environment with these distributions installed."""
        def is_installed(name : str, search_path : list[str]) -> bool:
            return name in installed

        with patch(f'{_MODULE}.FindTorchSitePackages', return_value=site_packages), \
                patch(f'{_MODULE}.IsInstalled', side_effect=is_installed):
            return HasMossRuntime(Path('/moss-env'))

    def test_package_with_dependencies_is_complete(self) -> None:
        """The package beside Torch with all its dependencies is the MOSS runtime."""
        installed = {MOSS_DISTRIBUTION, *(RequirementName(requirement) for requirement in MOSS_DEPENDENCIES)}

        self.assertLoggedTrue("runtime found", self._has_runtime(installed))

    def test_package_without_dependencies_is_incomplete(self) -> None:
        """Setup interrupted after installing the package leaves an environment that still needs its dependencies."""
        self.assertLoggedFalse("runtime not found", self._has_runtime({MOSS_DISTRIBUTION}))

    def test_dependencies_without_package_are_incomplete(self) -> None:
        """An environment with Transformers and the rest, but not MOSS itself, has no runtime."""
        installed = {RequirementName(requirement) for requirement in MOSS_DEPENDENCIES}

        self.assertLoggedFalse("runtime not found", self._has_runtime(installed))

    def test_environment_without_torch_has_no_runtime(self) -> None:
        """A directory with no Torch site-packages is not a MOSS environment."""
        self.assertLoggedFalse("runtime not found", self._has_runtime(set(), site_packages=None))
