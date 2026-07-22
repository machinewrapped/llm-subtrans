import os
import unittest
from unittest.mock import patch

from PySubtrans.Helpers.Resources import (
    ConfigureConfigDir,
    ConfigureConfigDirFromArguments,
    default_config_dir,
)
from PySubtrans.Helpers.TestCases import LoggedTestCase


class TestResources(LoggedTestCase):
    """Test application resource path selection."""

    def tearDown(self) -> None:
        """Restore the normal configuration directory after each test."""
        ConfigureConfigDir(config_path=default_config_dir)
        super().tearDown()

    @patch('PySubtrans.Helpers.Resources.os.path.isdir', return_value=False)
    @patch('PySubtrans.Helpers.Resources.os.getcwd', return_value=os.path.abspath('portable-app'))
    def test_portable_mode_uses_local_settings_directory(self, mock_getcwd, mock_isdir):
        """Portable mode stores settings below the current directory."""
        expected_path = os.path.abspath(os.path.join(os.path.abspath('portable-app'), '.settings'))

        result = ConfigureConfigDirFromArguments(['--portable'])

        self.assertLoggedEqual('portable configuration directory', expected_path, result)
        mock_getcwd.assert_called()
        mock_isdir.assert_not_called()

    @patch('PySubtrans.Helpers.Resources.os.path.isdir', return_value=True)
    @patch('PySubtrans.Helpers.Resources.os.getcwd', return_value=os.path.abspath('portable-app'))
    def test_existing_settings_directory_enables_portable_mode(self, mock_getcwd, mock_isdir):
        """An existing .settings directory enables portable mode automatically."""
        expected_path = os.path.abspath(os.path.join(os.path.abspath('portable-app'), '.settings'))

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


if __name__ == '__main__':
    unittest.main()
