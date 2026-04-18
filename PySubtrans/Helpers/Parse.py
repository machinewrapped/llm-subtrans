from typing import Any
import regex
import json
import logging

KEY_VALUE_SEPARATOR = "::"

def ParseKeyValuePairs(value : Any, separator : str = KEY_VALUE_SEPARATOR) -> dict[str,str]:
    """
    Parse a dict of (key, value) pairs from a dict, list, or newline-separated string.
    Each entry is split on the first occurrence of `separator`. Entries without the
    separator or with empty key/value are skipped.
    """
    if not value:
        return {}

    if isinstance(value, dict):
        return { str(k).strip(): str(v).strip() for k, v in value.items() if k and v }

    if isinstance(value, list):
        lines = value
    else:
        lines = str(value).splitlines()

    result : dict[str,str] = {}
    for line in lines:
        line = str(line).strip()
        if separator in line:
            key, _, val = line.partition(separator)
            key = key.strip()
            val = val.strip()
            if key and val:
                result[key] = val
    return result


def ParseKeyValuePairsOrFiles(entries : list[str], separator : str = KEY_VALUE_SEPARATOR) -> dict[str,str]:
    """
    Parse key/value pairs from a list of strings.

    Each entry is either:
    - a ``key::value`` inline pair, or
    - a file path whose contents are one ``key::value`` pair per line.

    Entries whose separator is absent are treated as file paths.
    File-not-found is logged as a warning; malformed lines inside a file raise ValueError.
    """
    result : dict[str,str] = {}
    for entry in entries:
        entry = str(entry).strip()
        if not entry:
            continue
        if separator in entry:
            result.update(ParseKeyValuePairs(entry, separator=separator))
        else:
            try:
                with open(entry, "r", encoding="utf-8", newline='') as f:
                    for line in (l.strip() for l in f if l.strip()):
                        if separator in line:
                            result.update(ParseKeyValuePairs(line, separator=separator))
                        else:
                            raise ValueError(f"Invalid key/value format in {entry!r}: {line!r}")
            except FileNotFoundError:
                logging.warning(f"Key-value file not found: {entry}")
    return result

def FormatKeyValuePairs(pairs : Any, separator : str = KEY_VALUE_SEPARATOR) -> str:
    """
    Format a dict as newline-separated key<separator>value pairs.
    """
    if not pairs:
        return ""
    return '\n'.join(f"{k}{separator}{v}" for k, v in pairs.items())

def ParseNames(name_list : str|list|None|Any) -> list[str]:
    """
    Parse a list of names from a string or list of strings
    """
    if name_list is None:
        return []

    if isinstance(name_list, str):
        name_list = regex.split(r"[\n,]\s*", name_list)

    if isinstance(name_list, list):
        # Split each string in the list by comma or newline
        return [name.strip() for name in name_list for name in regex.split(r"[\n,]\s*", name) if name.strip()]

    return []

def ParseDelayFromHeader(value : str) -> float:
    """
    Try to figure out how long a suggested retry-after is
    """
    if not isinstance(value, str):
        return 12.3

    match = regex.match(r"([0-9\.]+)(\w+)?", value)
    if not match:
        return 32.1

    try:
        delay, unit = match.groups()
        delay = float(delay)
        unit = unit.lower() if unit else 's'
        if unit == 's':
            pass
        elif unit == 'm':
            delay *= 60
        elif unit == 'ms':
            delay /= 1000
        else:
            logging.error(f"Unexpected time unit '{unit}'")
            return 6.66

        return max(1, delay)  # ensure at least 1 second

    except Exception as e:
        logging.error(f"Unexpected time value '{value}' ({e})")
        return 6.66

def ParseErrorMessageFromText(value: str) -> str|None:
    """
    Try to extract a human-friendly error message from an HTTP response body.

    Accepts raw text which may be:
    - A JSON object (e.g. {"error": {"message": "..."}})
    - A quoted JSON string (e.g. '\n{"error": {"message": "..."}}' )
    - Text containing an embedded JSON object

    Returns the extracted message string if found, otherwise None.
    """
    try:
        if not isinstance(value, str):
            return None

        text = value.strip()

        # If wrapped in single or double quotes, strip them
        if (text.startswith("'") and text.endswith("'")) or (text.startswith('"') and text.endswith('"')):
            text = text[1:-1]

        # Try direct JSON parse first
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
            # Fallback: try to locate an embedded JSON object
            brace_start = text.find('{')
            brace_end = text.rfind('}')
            if brace_start != -1 and brace_end > brace_start:
                try:
                    data = json.loads(text[brace_start:brace_end + 1])
                except json.JSONDecodeError:
                    pass  # data remains None

        # If JSON parsed, try common locations for an error message
        if isinstance(data, dict):
            # Common: {"error": {"message": "..."}}
            err = data.get('error')
            if isinstance(err, dict):
                msg = err.get('message')
                if isinstance(msg, str) and msg.strip():
                    return msg.strip()
                # Some providers may use 'Error' or different casing
                for key in ('Message', 'msg', 'description', 'detail', 'error_message'):
                    val = err.get(key)
                    if isinstance(val, str) and val.strip():
                        return val.strip()

            # Sometimes the message is at top-level
            for key in ('message', 'error_message', 'detail', 'description'):
                val = data.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()

        # Regex fallback: find "message":"..." handling escaped quotes
        match = regex.search(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        if match:
            raw = match.group(1)
            try:
                # Unescape JSON string content
                return json.loads(f'"{raw}"')
            except Exception:
                return raw

        return None

    except Exception as e:
        logging.debug(f"ParseErrorMessageFromText failed: {e}")
        return None

