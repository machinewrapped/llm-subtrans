import logging

try:
    from PyInstaller.utils.hooks import collect_submodules  # type: ignore

    hiddenimports = collect_submodules('PySubtrans.Providers')
    hiddenimports += collect_submodules('PySubtrans.Formats')

    # qwen_asr is imported dynamically via importlib.import_module so
    # PyInstaller's static analyser never follows the chain.  Seeding
    # the package here lets hook-qwen_asr.py fire and collect its data.
    hiddenimports += ['qwen_asr']

    # Torch is excluded from static analysis entirely (see the exclusion below), so PyInstaller can't see that it internally imports unittest.mock at runtime -- for ordinary compile/dispatch bookkeeping in torch._inductor, torch._dispatch.python and torch._guards, not just for tests.
    # The external Torch venv only contributes its site-packages to sys.path, not its stdlib, so the frozen bundle has to carry unittest.mock itself.
    # Without it, Qwen Local transcription fails at runtime with "No module named 'unittest.mock'" the moment torch code touches it.
    # Naming just the submodule still pulls in the whole unittest package, since importing it runs unittest/__init__.py first.
    hiddenimports += ['unittest.mock']

    # Torch is installed separately for frozen Qwen Local deployments.  Keep
    # both Python packages and their native payloads out of the application;
    # the runtime loader adds a compatible external installation explicitly.
    excludedimports = ['torch', 'torchgen']

except ImportError:
    logging.info("PyInstaller not found, skipping hook")
