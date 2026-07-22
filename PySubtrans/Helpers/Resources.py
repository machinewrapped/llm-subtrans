
from collections.abc import Sequence
import os
import sys
import appdirs # type: ignore

default_config_dir : str = appdirs.user_config_dir("LLMSubtrans", "MachineWrapped", roaming=True)
config_dir : str = default_config_dir


def GetConfigDir() -> str:
    """Return the active application configuration directory."""
    return config_dir


def GetSettingsPath() -> str:
    """Return the path to the active application settings file."""
    return os.path.join(config_dir, "settings.json")


def _get_portable_config_dir() -> str:
    """Return the configuration directory used by portable installations."""
    return os.path.abspath(os.path.join(os.getcwd(), ".settings"))


def ConfigureConfigDir(config_path : str|None = None, portable : bool = False) -> str:
    """Configure the application directory used for persistent settings and logs."""
    global config_dir

    if config_path:
        config_dir = os.path.abspath(os.path.expanduser(config_path))
    elif portable or os.path.isdir(_get_portable_config_dir()):
        config_dir = _get_portable_config_dir()
    else:
        config_dir = default_config_dir

    return config_dir


def ConfigureConfigDirFromArguments(arguments : Sequence[str]|None = None) -> str:
    """Configure the application directory from early command-line arguments."""
    arguments = list(arguments if arguments is not None else sys.argv[1:])
    config_path : str|None = None
    portable = False

    for index, argument in enumerate(arguments):
        if argument == "--portable":
            portable = True
        elif argument == "--configpath" and index + 1 < len(arguments):
            config_path = arguments[index + 1]
        elif argument.startswith("--configpath="):
            config_path = argument.split("=", 1)[1]

    if config_path is None and not portable:
        config_path = os.getenv("LLM_SUBTRANS_CONFIG_DIR") or None

    return ConfigureConfigDir(config_path=config_path, portable=portable)

def GetResourcePath(relative_path : str, *parts : str) -> str:
    """
    Locate a resource file or folder in the application directory or the PyInstaller bundle.
    """
    if hasattr(sys, "_MEIPASS"):
        # Running in a PyInstaller bundle
        return os.path.join(sys._MEIPASS, relative_path, *parts) # type: ignore

    return os.path.join(os.path.abspath("."), relative_path or "", *parts)

