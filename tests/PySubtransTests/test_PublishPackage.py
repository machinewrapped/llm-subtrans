import subprocess
import sys
from argparse import Namespace
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import skip_if_debugger_attached
from scripts import publish_package


class TestPublishPackage(LoggedTestCase):
    """Release validation must finish successfully before building or uploading."""

    def setUp(self) -> None:
        super().setUp()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.mocks = {}
        for name in ('WritePackageToml', 'PrintSummary', 'EnsureBuildTools',
                     'CleanBuildArtifacts', 'BuildPackage', 'UploadPackage'):
            self.mocks[name] = self.stack.enter_context(patch.object(publish_package, name))
        self.stack.enter_context(patch.object(publish_package, 'LoadToml', return_value={}))
        self.stack.enter_context(patch.object(publish_package, 'GetPackageVersion', return_value='1.0'))
        self.stack.enter_context(patch.object(publish_package, 'Confirm', return_value=True))
        self.args = Namespace(skip_upload=False, yes=True, repository=None)
        self.stack.enter_context(patch.object(publish_package, 'ParseArguments', return_value=self.args))
        self.mock_run = self.stack.enter_context(patch.object(publish_package.subprocess, 'run'))

    def test_both_suites_precede_build(self) -> None:
        """Build-only publishing still validates both suites first."""
        self.args.skip_upload = True
        events = []
        self.mock_run.side_effect = lambda command, **kwargs: events.append(Path(command[1]).name)
        self.mocks['BuildPackage'].side_effect = lambda path: events.append('build')
        publish_package.Main()
        self.assertLoggedEqual('release order', ['unit_tests.py', 'integration_tests.py', 'build'], events)
        self.assertLoggedEqual('no upload requested', 0, self.mocks['UploadPackage'].call_count)
        for call in self.mock_run.call_args_list:
            self.assertLoggedEqual('active interpreter', sys.executable, call.args[0][0])
            self.assertLoggedEqual('failure propagation', True, call.kwargs['check'])
            self.assertLoggedEqual('checkout cwd', Path(publish_package.__file__).resolve().parent.parent,
                                   call.kwargs['cwd'])

    @skip_if_debugger_attached
    def test_failed_suite_blocks_build_and_upload(self) -> None:
        """A failure in either suite prevents destructive cleanup and release actions."""
        for failing_suite in ('unit_tests.py', 'integration_tests.py'):
            with self.subTest(suite=failing_suite):
                def Run(command : list[str], **kwargs) -> None:
                    if Path(command[1]).name == failing_suite:
                        raise subprocess.CalledProcessError(1, command)
                self.mock_run.side_effect = Run
                with self.assertRaises(subprocess.CalledProcessError):
                    publish_package.Main()
                for name in ('CleanBuildArtifacts', 'BuildPackage', 'UploadPackage'):
                    self.assertLoggedEqual(name + ' blocked', 0, self.mocks[name].call_count)
