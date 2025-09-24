from __future__ import annotations
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, TypeAlias

import regex

from PySubtrans.Helpers.Time import GetTimeDelta

BasicType: TypeAlias = str | int | float | bool | list[str] | None
SettingType: TypeAlias = BasicType | dict[str, 'SettingType'] | dict[str, 'SettingsType']
GuiSettingsType: TypeAlias = dict[str, tuple[type|str|list[str], str]]

class SettingsError(Exception):
    """Raised when a setting cannot be coerced to the expected type."""
    pass

class SettingsType(dict[str, SettingType]):
    """
    Settings dictionary with restricted range of types allowed and type-safe getters
    """
    def __init__(self, settings : Mapping[str,SettingType]|None = None):
        if not isinstance(settings, SettingsType):
            settings = dict(settings or {})
        super().__init__(settings)

    def get_bool(self, key: str, default: bool|None = False) -> bool:
        """Get a boolean setting with type safety"""
        value = self.get(key, default)
        if value is None:
            return False
        
        if isinstance(value, bool):
            return value
        elif isinstance(value, str):
            lower_val = value.lower()
            if lower_val == 'true':
                return True
            elif lower_val == 'false':
                return False

        raise SettingsError(f"Cannot convert setting '{key}' of type {type(value).__name__} with value {repr(value)} to bool")

    def get_int(self, key: str, default: int|None = None) -> int|None:
        """Get an integer setting with type safety"""
        value = self.get(key, default)
        if value is None:
            return None

        if isinstance(value, (int,float)):
            return int(value)
        elif isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                pass

        raise SettingsError(f"Cannot convert setting '{key}' of type {type(value).__name__} with value {repr(value)} to int")

    def get_float(self, key: str, default: float|None = None) -> float|None:
        """Get a float setting with type safety"""
        value = self.get(key, default)
        if value is None:
            return None
        
        if isinstance(value, (int, float)):
            return float(value)
        elif isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                pass

        raise SettingsError(f"Cannot convert setting '{key}' of type {type(value).__name__} with value {repr(value)} to float")

    def get_str(self, key: str, default: str|None = None) -> str|None:
        """Get a string setting with type safety"""
        value = self.get(key, default)
        if value is None:
            return None
        elif isinstance(value, str):
            return value
        elif isinstance(value, (int, float, bool)):
            return str(value)
        elif isinstance(value, list):
            return ', '.join(str(v) for v in value)

        return str(value)

    def get_timedelta(self, key: str, default: timedelta) -> timedelta:
        """Get a timedelta setting with type safety"""
        value = self.get(key, default)
        if value is None:
            return default
        if isinstance(value, timedelta):
            return value
        elif isinstance(value, (int, float, str)):
            result = GetTimeDelta(value)
            if isinstance(result, timedelta):
                return result    

        raise SettingsError(f"Cannot convert setting '{key}' of type {type(value).__name__} to timedelta")

    def get_str_list(self, key: str, default: list[str]|None = None) -> list[str]:
        """Get a list of strings setting with type safety"""
        if default is None:
            default = []

        value = self.get_list(key, default)

        if all(isinstance(item, str) for item in value):
            return value

        return [ str(item).strip() for item in value if item is not None ]

    def get_list(self, key: str, default: list[Any]|None = None) -> list[Any]:
        """Get a list setting with type safety"""
        value = self.get(key, default)
        if value is None:
            return []
        
        if isinstance(value, list):
            return value
        elif isinstance(value, (tuple, set)):
            return list(value)
        elif isinstance(value, str):
            # Try to split string by common separators
            values = regex.split(r'[;,]', value)
            return [ v.strip() for v in values if v.strip() ]

        raise SettingsError(f"Cannot convert setting '{key}' of type {type(value).__name__} to list")

    def get_dict(self, key: str, default: SettingsType|None = None) -> SettingsType:
        """Get a dict setting with type safety - returns mutable reference when possible"""
        value = self.get(key, default)
        if value is None:
            return default or SettingsType()
        if isinstance(value, SettingsType):
            # Return the actual SettingsType object for mutable access
            return value
        elif isinstance(value, dict):
            # Convert to SettingsType and store it back for mutable access
            value = SettingsType(value)
            self[key] = value
            return value
        elif value is None:
            # Create a new dictionary if not present
            value = default or SettingsType()
            self[key] = value
            return value
        else:
            raise TypeError(f"Setting '{key}' is not a dict")

    def add(self, setting: str, value: Any) -> None:
        """Add a setting to the settings dictionary"""
        self[setting] = value

    def set(self, setting: str, value: Any) -> None:
        """Set a setting in the settings dictionary"""
        self[setting] = value

    def update(self, other=(), /, **kwds) -> None:
        """Update settings, filtering out None values"""
        # Match dict.update signature: update([other,] **kwds)
        if hasattr(other, 'items'):
            if isinstance(other, SettingsType):
                other = dict(other)
            # Filter None values for our settings
            if isinstance(other, dict):
                other = {k: v for k, v in other.items() if v is not None}
        super().update(other, **kwds)

def redact_sensitive_values(settings : SettingsType) -> SettingsType:
    """
    Return a copy of settings with any potential secrets redacted.
    """
    redacted : SettingsType = SettingsType()
    for key, value in settings.items():
        if isinstance(value, SettingsType):
            redacted[key] = redact_sensitive_values(value)
        elif any(s in key.lower() for s in ('key', 'token', 'password', 'secret', 'auth', 'credential')):
            redacted[key] = '***'
        else:
            redacted[key] = value
    return redacted
