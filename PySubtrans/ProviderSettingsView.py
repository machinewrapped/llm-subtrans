"""
Provider settings view for type-safe mutable access to provider configurations.
"""

from __future__ import annotations
from collections.abc import MutableMapping
from typing import Any
import logging

from PySubtrans.SettingsType import SettingType, SettingsType
from PySubtrans.Helpers.Localization import _


class ProviderSettingsView(MutableMapping[str, SettingsType]):
    """Type-safe mutable view of provider settings"""
    
    def __init__(self, parent_dict: dict[str, SettingType], key: str = 'provider_settings'):
        self._parent = parent_dict
        self._key = key
        # Ensure the key exists and is a dict
        if key not in parent_dict or not isinstance(parent_dict[key], dict):
            parent_dict[key] = SettingsType()
    
    def __getitem__(self, provider: str) -> SettingsType:
        provider_dict = self._parent[self._key]
        if not isinstance(provider_dict, dict):
            raise KeyError(f"Provider settings is not a dict: {type(provider_dict)}")
        
        settings = provider_dict.get(provider)
        if settings is None:
            raise KeyError(provider)
        
        if isinstance(settings, SettingsType):
            return settings
        elif isinstance(settings, dict):
            # Convert to SettingsType and update the parent
            settings_type = SettingsType(settings)
            provider_dict[provider] = settings_type
            return settings_type
        else:
            raise ValueError(f"Invalid provider settings type for {provider}: {type(settings)}")
    
    def __setitem__(self, provider: str, settings: SettingsType | dict[str, Any]) -> None:
        provider_dict = self._parent[self._key]
        if not isinstance(provider_dict, dict):
            self._parent[self._key] = SettingsType()
            provider_dict = self._parent[self._key]
        
        if not isinstance(settings, SettingsType):
            if isinstance(settings, dict):
                settings = SettingsType(settings)
            else:
                raise ValueError(f"Provider settings must be SettingsType or dict, got {type(settings)}")
        
        # Ensure provider_dict is definitely a dict before assignment
        if isinstance(provider_dict, dict):
            provider_dict[provider] = settings
        else:
            logging.error(_("Provider settings container is not a dictionary"))
            raise TypeError("Provider settings container is not a dictionary")
    
    def __delitem__(self, provider: str) -> None:
        provider_dict = self._parent[self._key]
        if not isinstance(provider_dict, dict):
            raise KeyError(provider)
        del provider_dict[provider]
    
    def __iter__(self):
        provider_dict = self._parent[self._key]
        if isinstance(provider_dict, dict):
            return iter(provider_dict)
        return iter([])
    
    def __len__(self) -> int:
        provider_dict = self._parent[self._key]
        if isinstance(provider_dict, dict):
            return len(provider_dict)
        return 0
    
    def __contains__(self, provider: Any) -> bool:
        """Check if provider exists in settings"""
        if not isinstance(provider, str):
            return False
        provider_dict = self._parent[self._key]
        if not isinstance(provider_dict, dict):
            return False
        return provider in provider_dict
    
    def get_with_default(self, provider: str, default: SettingsType | None = None) -> SettingsType | None:
        """Get provider settings with optional default"""
        try:
            return self[provider]
        except KeyError:
            return default or SettingsType() if default is None else default