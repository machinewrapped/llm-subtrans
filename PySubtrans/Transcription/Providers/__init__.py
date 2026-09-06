"""
PySubtrans.Transcription.Providers - Transcription service implementations.

Explicit imports ensure all providers register regardless of install method.
Each module self-guards on its optional dependencies (see Provider_QwenLocal).
"""

# pyright: reportUnusedImport=false

from . import Provider_QwenLocal
from . import Provider_OpenRouter
from . import Provider_OpenAI
from . import Provider_Gemini
