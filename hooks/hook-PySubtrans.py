import importlib.util
import logging
import sys

# Standard library modules that neither the application nor its external Torch environment needs
_UNUSED_STDLIB = {
    'antigravity', 'curses', '_curses', '_curses_panel', 'ensurepip', 'idlelib', 'lib2to3',
    'pydoc_data', '_pyrepl', 'test', 'this', 'tkinter', '_tkinter', 'turtle', 'turtledemo', 'venv',
}

def _is_test_module(name : str) -> bool:
    """Whether a standard library module is part of CPython's own test suite."""
    parts = name.split('.')
    return parts[0].startswith(('_test', '_xx', 'xx')) or any(part in ('test', 'tests', 'idle_test') for part in parts)

try:
    from PyInstaller.utils.hooks import collect_submodules  # type: ignore

    hiddenimports = collect_submodules('PySubtrans.Providers')
    hiddenimports += collect_submodules('PySubtrans.Formats')

    # Torch and the Qwen runtime load from the external Torch environment, outside PyInstaller's analysis.
    # That environment only contributes its site-packages to sys.path, not a standard library, so the bundle carries all of it.
    # Otherwise any stdlib module the app itself never imports fails at runtime, as unittest.mock did for Torch.
    for module_name in sorted(sys.stdlib_module_names):
        if module_name in _UNUSED_STDLIB or _is_test_module(module_name):
            continue

        spec = importlib.util.find_spec(module_name)
        if spec is None:
            continue

        if spec.submodule_search_locations:
            hiddenimports += collect_submodules(module_name, filter=lambda name: not _is_test_module(name), on_error='ignore')
        else:
            hiddenimports.append(module_name)

    # Torch is installed separately for frozen Qwen Local deployments.  Keep
    # both Python packages and their native payloads out of the application;
    # the runtime loader adds a compatible external installation explicitly.
    excludedimports = ['torch', 'torchgen']

except ImportError:
    logging.info("PyInstaller not found, skipping hook")
