import os
import sys
import unittest
from unittest.mock import patch

from PySubtrans.Helpers.Resources import (
    ConfigureConfigDir,
    ConfigureConfigDirFromArguments,
    GetAppDir,
    default_config_dir,
)
from PySubtrans.Helpers.TestCases import LoggedTestCase


class TestResources(LoggedTestCase):
    """Test application resource path selection."""

    _PORTABLE_APP_DIR : str = os.path.abspath('portable-app')

    def tearDown(self) -> None:
        """Restore the normal configuration directory after each test."""
        ConfigureConfigDir(config_path=default_config_dir)
        super().tearDown()

    @patch('PySubtrans.Helpers.Resources.os.path.isdir', return_value=False)
    @patch('PySubtrans.Helpers.Resources.os.getcwd', return_value=_PORTABLE_APP_DIR)
    def test_portable_mode_uses_local_settings_directory(self, mock_getcwd, mock_isdir):
        """Portable mode stores settings below the current directory."""
        # NOTE: os.getcwd is patched on the shared os module for the duration of this test,
        # so the expected path must not be built with another live os.path.abspath() call.
        expected_path = os.path.join(self._PORTABLE_APP_DIR, '.settings')

        result = ConfigureConfigDirFromArguments(['--portable'])

        self.assertLoggedEqual('portable configuration directory', expected_path, result)
        mock_getcwd.assert_called()
        mock_isdir.assert_not_called()

    @patch('PySubtrans.Helpers.Resources.os.path.isdir', return_value=True)
    @patch('PySubtrans.Helpers.Resources.os.getcwd', return_value=_PORTABLE_APP_DIR)
    def test_existing_settings_directory_enables_portable_mode(self, mock_getcwd, mock_isdir):
        """An existing .settings directory enables portable mode automatically."""
        expected_path = os.path.join(self._PORTABLE_APP_DIR, '.settings')

        result = ConfigureConfigDirFromArguments([])

        self.assertLoggedEqual('automatic portable configuration directory', expected_path, result)
        mock_getcwd.assert_called()
        mock_isdir.assert_called()

    @patch('PySubtrans.Helpers.Resources.os.path.isdir', return_value=True)
    def test_configpath_overrides_portable_mode(self, mock_isdir):
        """An explicit config path takes precedence over portable mode detection."""
        config_path = os.path.abspath(os.path.join('custom', 'settings'))

        result = ConfigureConfigDirFromArguments(['--portable', '--configpath', config_path])

        self.assertLoggedEqual('explicit configuration directory', config_path, result)
        mock_isdir.assert_not_called()

    def test_configpath_equals_syntax_is_supported(self):
        """The equals form of --configpath is accepted before full argument parsing."""
        config_path = os.path.abspath(os.path.join('custom', 'settings'))

        result = ConfigureConfigDirFromArguments([f'--configpath={config_path}'])

        self.assertLoggedEqual('equals-form configuration directory', config_path, result)

    @patch.dict('os.environ', {'LLM_SUBTRANS_CONFIG_PATH': os.path.abspath(os.path.join('environment', 'settings'))})
    @patch('PySubtrans.Helpers.Resources.os.path.isdir', return_value=False)
    def test_environment_config_dir_is_used_when_no_argument_is_set(self, mock_isdir):
        """Use the installer-provided environment path when no CLI override is present."""
        expected_path = os.path.abspath(os.path.join('environment', 'settings'))

        result = ConfigureConfigDirFromArguments([])

        self.assertLoggedEqual('environment configuration directory', expected_path, result)
        mock_isdir.assert_not_called()


class TestGetAppDir(LoggedTestCase):
    """Test application directory resolution."""

    @patch.object(sys, 'frozen', True, create=True)
    @patch.object(sys, 'executable', os.path.join('C:', os.sep, 'Apps', 'gui-subtrans', 'gui-subtrans.exe'))
    @patch('PySubtrans.Helpers.Resources.os.path.realpath', side_effect=lambda p: p)
    def test_frozen_build_returns_executable_parent(self, _mock_realpath):
        """Frozen builds place the torch env beside the executable."""
        expected = os.path.join('C:', os.sep, 'Apps', 'gui-subtrans')

        result = GetAppDir()

        self.assertLoggedEqual('frozen app directory', expected, result)

    def test_dev_mode_returns_current_working_directory(self):
        """Development runs use the current working directory."""
        # Ensure sys.frozen is not set (normal dev state)
        frozen = getattr(sys, 'frozen', None)
        if frozen is not None:
            delattr(sys, 'frozen')

        try:
            result = GetAppDir()

            self.assertLoggedEqual('dev app directory', os.path.abspath('.'), result)
        finally:
            if frozen is not None:
                sys.frozen = frozen  # type: ignore[attr-defined]


if __name__ == '__main__':
    unittest.main()
