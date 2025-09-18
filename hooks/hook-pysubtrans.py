import logging

try:
    from PyInstaller.utils.hooks import collect_submodules  # type: ignore

    hiddenimports = collect_submodules('scripts')
    hiddenimports += collect_submodules('PySubtrans.Providers')
    hiddenimports += collect_submodules('PySubtrans.Formats')

except ImportError:
    logging.info("PyInstaller not found, skipping hook")