from __future__ import annotations
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, TypeAlias

BasicType: TypeAlias = str | int | float | bool | list[str] | None
SettingType: TypeAlias = BasicType | dict[str, 'SettingType'] | dict[str, 'SettingsType']
GuiSettingsType: TypeAlias = dict[str, tuple[type|str|list[str], str]]

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
        from .Helpers.Settings import GetBoolSetting
        return GetBoolSetting(self, key, default)

    def get_int(self, key: str, default: int|None = None) -> int|None:
        """Get an integer setting with type safety"""
        from .Helpers.Settings import GetIntSetting
        return GetIntSetting(self, key, default)

    def get_float(self, key: str, default: float|None = None) -> float|None:
        """Get a float setting with type safety"""
        from .Helpers.Settings import GetFloatSetting
        return GetFloatSetting(self, key, default)

    def get_str(self, key: str, default: str|None = None) -> str|None:
        """Get a string setting with type safety"""
        from .Helpers.Settings import GetStrSetting
        return GetStrSetting(self, key, default)

    def get_timedelta(self, key: str, default: timedelta) -> timedelta:
        """Get a timedelta setting with type safety"""
        from .Helpers.Settings import GetTimeDeltaSetting
        return GetTimeDeltaSetting(self, key, default)

    def get_str_list(self, key: str, default: list[str]|None = None) -> list[str]:
        """Get a list of strings setting with type safety"""
        from .Helpers.Settings import GetStringListSetting
        return GetStringListSetting(self, key, default or [])

    def get_list(self, key: str, default: list[Any]|None = None) -> list[Any]:
        """Get a list setting with type safety"""
        from .Helpers.Settings import GetListSetting
        return GetListSetting(self, key, default or [])

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
