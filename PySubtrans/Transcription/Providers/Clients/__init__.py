"""
PySubtrans.Transcription.Providers.Clients - Transcription client implementations

This module contains all client implementations for transcription providers.
Provider modules own registration, settings, catalogs and the pure payload
helpers (kept SDK-free for fast imports and unit tests); clients own backend
communication and import shared helpers from their provider. Providers load
their client lazily in GetTranscriptionClient so registration never pays for
heavy optional SDKs.
"""
