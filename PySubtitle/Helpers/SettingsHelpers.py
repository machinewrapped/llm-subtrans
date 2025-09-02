"""
Type-safe settings retrieval and coercion functions.

This module provides helper functions to safely retrieve and coerce settings
from dictionaries to specific types, with proper error handling for type
incompatibilities.
"""

from typing import Any, TypeVar, overload, Mapping
from datetime import timedelta

import regex

from PySubtitle.Helpers.Time import GetTimeDelta, GetTimeDeltaSafe
from PySubtitle.Options import Options
from PySubtitle.SettingsType import SettingType, SettingsType

T = TypeVar('T')

class SettingsError(Exception):
    """Raised when a setting cannot be coerced to the expected type."""
    pass

@overload
def GetBoolSetting(settings: SettingsType|Mapping[str, SettingType]|Options, key: str) -> bool: ...

@overload
def GetBoolSetting(settings: SettingsType|Mapping[str, SettingType]|Options, key: str, default: bool|None) -> bool: ...

def GetBoolSetting(settings: SettingsType|Mapping[str, SettingType]|Options, key: str, default: bool|None = False) -> bool:
    """
    Safely retrieve a boolean setting from a settings dictionary.
    
    Args:
        settings: The settings dictionary
        key: The setting key
        default: Default value if key is not present
        
    Returns:
        Boolean value of the setting
        
    Raises:
        SettingsError: If the setting cannot be converted to bool
    """
    value = settings.get(key, default)
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


@overload
def GetIntSetting(settings: SettingsType|Mapping[str, SettingType]|Options, key: str) -> int|None: ...

@overload 
def GetIntSetting(settings: SettingsType|Mapping[str, SettingType]|Options, key: str, default: int|None) -> int|None: ...

def GetIntSetting(settings: SettingsType|Mapping[str, SettingType]|Options, key: str, default: int|None = 0) -> int|None:
    """
    Safely retrieve an integer setting from a settings dictionary.
    
    Args:
        settings: The settings dictionary
        key: The setting key
        default: Default value if key is not present
        
    Returns:
        Integer value of the setting
        
    Raises:
        SettingsError: If the setting cannot be converted to int
    """
    value = settings.get(key, default)
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


@overload
def GetFloatSetting(settings: SettingsType|Mapping[str, SettingType]|Options, key: str) -> float|None: ...

@overload
def GetFloatSetting(settings: SettingsType|Mapping[str, SettingType]|Options, key: str, default: float|None) -> float|None: ...

def GetFloatSetting(settings: SettingsType|Mapping[str, SettingType]|Options, key: str, default: float|None = None) -> float|None:
    """
    Safely retrieve a float setting from a settings dictionary.
    
    Args:
        settings: The settings dictionary
        key: The setting key
        default: Default value if key is not present
        
    Returns:
        Float value of the setting
        
    Raises:
        SettingsError: If the setting cannot be converted to float
    """
    value = settings.get(key, default)
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

@overload
def GetStrSetting(settings: SettingsType|Mapping[str, SettingType]|Options, key: str) -> str|None: ...

@overload
def GetStrSetting(settings: SettingsType|Mapping[str, SettingType]|Options, key: str, default: str|None) -> str|None: ...

def GetStrSetting(settings: SettingsType|Mapping[str, SettingType]|Options, key: str, default: str|None = None) -> str|None:
    """
    Safely retrieve a string setting from a settings dictionary.
    
    Args:
        settings: The settings dictionary
        key: The setting key
        default: Default value if key is not present
        
    Returns:
        String value of the setting or None
        
    Raises:
        SettingsError: If the setting cannot be converted to str
    """
    value = settings.get(key, default)
    if value is None:
        return None
    elif isinstance(value, str):
        return value
    elif isinstance(value, (int, float, bool)):
        return str(value)
    elif isinstance(value, list):
        return ', '.join(str(v) for v in value)

    return str(value)

@overload
def GetListSetting(settings: SettingsType|Mapping[str, SettingType]|Options, key: str) -> list[Any]: ...

@overload
def GetListSetting(settings: SettingsType|Mapping[str, SettingType]|Options, key: str, default: list[Any]) -> list[Any]: ...

def GetListSetting(settings: SettingsType|Mapping[str, SettingType]|Options, key: str, default: list[Any]|None = None) -> list[Any]:
    """
    Safely retrieve a list setting from a settings dictionary.
    
    Args:
        settings: The settings dictionary
        key: The setting key
        default: Default value if key is not present
        
    Returns:
        List value of the setting
        
    Raises:
        SettingsError: If the setting cannot be converted to list
    """
    value = settings.get(key, default)
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

def GetStringListSetting(settings: SettingsType|Mapping[str, SettingType]|Options, key: str, default: list[str]|None = None) -> list[str]:
    """
    Safely retrieve a list of strings setting from a settings dictionary.
    
    Args:
        settings: The settings dictionary
        key: The setting key
        default: Default value if key is not present
        
    Returns:
        List of strings value of the setting
        
    Raises:
        SettingsError: If the setting cannot be converted to list of strings
    """
    if default is None:
        default = []

    value = GetListSetting(settings, key, default)

    if all(isinstance(item, str) for item in value):
        return value

    return [ str(item).strip() for item in value if item is not None ]

def GetTimeDeltaSetting(settings: SettingsType|Mapping[str, SettingType]|Options, key: str, default: timedelta = timedelta(seconds=0)) -> timedelta:
    """
    Safely retrieve a timedelta setting from a settings dictionary.
    The setting value is expected to be in seconds as a float.
    
    Args:
        settings: The settings dictionary
        key: The setting key
        default: Default value in seconds if key is not present
        
    Returns:
        timedelta object
        
    Raises:
        SettingsError: If the setting cannot be converted to timedelta
    """
    value = settings.get(key, default)
    if value is None:
        return default
    if isinstance(value, timedelta):
        return value
    elif isinstance(value, (int, float, str)):
        result = GetTimeDelta(value)
        if isinstance(result, timedelta):
            return result    

    raise SettingsError(f"Cannot convert setting '{key}' of type {type(value).__name__} to timedelta")

def get_optional_setting(settings: SettingsType|Mapping[str, SettingType]|Options, key: str, setting_type: type[T]) -> T | None:
    """
    Safely retrieve an optional setting that may not be present.
    
    Args:
        settings: The settings dictionary
        key: The setting key
        setting_type: The expected type of the setting
        
    Returns:
        The setting value of the specified type, or None if not present
        
    Raises:
        SettingsError: If the setting is present but cannot be converted to the expected type
    """
    if isinstance(settings, Options):
        settings = SettingsType(settings)

    if key not in settings:
        return None
        
    value = settings[key]
    if value is None:
        return None
        
    # Map types to appropriate getter functions
    if setting_type == bool:
        return settings.get_bool(key)  # type: ignore
    elif setting_type == int:
        return settings.get_int(key)  # type: ignore
    elif setting_type == float:
        return settings.get_float(key)  # type: ignore
    elif setting_type == str:
        return settings.get_str(key)  # type: ignore
    elif setting_type == list:
        return GetListSetting(settings, key)  # type: ignore
    else:
        # For other types, try direct conversion
        if isinstance(value, setting_type):
            return value
        else:
            raise SettingsError(f"Cannot convert setting '{key}' of type {type(value).__name__} to {setting_type.__name__}")


def validate_setting_type(settings: SettingsType|Mapping[str, SettingType]|Options, key: str, expected_type: type[T], required: bool = False) -> bool:
    """
    Validate that a setting can be converted to the expected type without actually converting it.
    
    Args:
        settings: The settings dictionary
        key: The setting key
        expected_type: The expected type
        required: Whether the setting is required to be present
        
    Returns:
        True if the setting is valid or not present (when not required)
        
    Raises:
        SettingsError: If validation fails
    """
    if isinstance(settings, Options):
        settings = dict(settings)

    if key not in settings:
        if required:
            raise SettingsError(f"Required setting '{key}' is missing")
        return True
    
    try:
        get_optional_setting(settings, key, expected_type)
        return True
    except SettingsError:
        return False