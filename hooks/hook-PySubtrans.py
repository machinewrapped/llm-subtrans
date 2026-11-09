import logging

try:
    from PyInstaller.utils.hooks import collect_data_files, collect_submodules  # type: ignore

    # Standalone workers run under an external Python, so they must exist on disk.
    datas = collect_data_files('PySubtrans', includes=['Transcription/Workers/*.py'], include_py_files=True)

    hiddenimports = collect_submodules('PySubtrans.Providers')
    hiddenimports += collect_submodules('PySubtrans.Formats')

    # Torch is installed separately for frozen Qwen and MOSS deployments. Keep
    # its Python packages and native payloads out of the application bundle.
    excludedimports = ['torch', 'torchgen']

except ImportError:
    logging.info('PyInstaller not found, skipping hook')
