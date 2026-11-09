"""Pip requirement helpers shared by the local transcription runtimes.

Pure logic with no Torch or Qt imports.
"""

from importlib import metadata

import regex

_REQUIREMENT_NAME_PATTERN = regex.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*')


def RequirementName(requirement : str) -> str:
    """Return the normalised distribution name of a pip requirement."""
    match = _REQUIREMENT_NAME_PATTERN.match(requirement.strip())
    name = match.group(0) if match else requirement.strip()
    return regex.sub(r'[-_.]+', '-', name).lower()


def IsInstalled(distribution_name : str, search_path : list[str]) -> bool:
    """Whether a distribution is installed on the search path."""
    return next(iter(metadata.distributions(name=distribution_name, path=search_path)), None) is not None
