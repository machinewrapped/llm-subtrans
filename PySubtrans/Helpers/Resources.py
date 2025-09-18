
import os
import sys
import appdirs # type: ignore

old_config_dir : str = appdirs.user_config_dir("GPTSubtrans", "MachineWrapped", roaming=True)
config_dir : str = appdirs.user_config_dir("LLMSubtrans", "MachineWrapped", roaming=True)

def GetResourcePath(relative_path : str, *parts : str) -> str:
    """
    Locate a resource file or folder in the application directory or the PyInstaller bundle.
    """
    if hasattr(sys, "_MEIPASS"):
        # Running in a PyInstaller bundle
        return os.path.join(sys._MEIPASS, relative_path, *parts) # type: ignore

    return os.path.join(os.path.abspath("."), relative_path or "", *parts)

