"""
Test package initialisation.

Redirects the application settings directory to a sandbox before any test
module is imported, so no test can ever read or overwrite the user's real
settings file, no matter which code path (present or future) triggers a
settings save or load.
"""
import os
import tempfile

from PySubtrans.Helpers.Resources import ConfigureConfigDir, GetConfigDir, default_config_dir


def _configure_test_settings_sandbox() -> str:
    """
    Point the application config directory at a stable per-user sandbox
    under the system temp directory for the whole test process.
    """
    sandbox_dir = os.path.join(tempfile.gettempdir(), "LLMSubtransTestSettings")
    os.makedirs(sandbox_dir, exist_ok=True)
    return ConfigureConfigDir(config_path=sandbox_dir)


_sandbox_dir = _configure_test_settings_sandbox()

if GetConfigDir() == default_config_dir:
    raise RuntimeError("Test settings sandbox was not applied: tests would use the real settings file")
