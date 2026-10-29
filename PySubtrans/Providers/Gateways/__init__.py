"""
PySubtrans.Providers.Gateways - Gateways that route translation requests to models from many makers

Each gateway is a module with a GatewayDefinition and a one-line subclass of GatewayProvider.
See docs/translation-provider-integration.md before adding one.
"""

# pyright: reportUnusedImport=false

# Explicitly import each gateway so it is registered
from . import APIRoute
from . import AtlasCloud
from . import DemonRoute
from . import Opper
from . import Requesty
