"""
PySubtrans.Formats - Format-specific file handlers

This module contains all file format handling logic, isolating format-specific
dependencies from the core business logic.
"""

# Explicitly import all format handler modules to ensure they're registered
# This is required for pip-installed packages where dynamic discovery may fail
from . import SrtFileHandler
from . import SSAFileHandler
from . import VttFileHandler