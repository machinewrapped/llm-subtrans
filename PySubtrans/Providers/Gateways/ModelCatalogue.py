from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class FamilySource(Enum):
    """
    How catalogue entries are grouped into model families.
    """
    IdPrefix = 'id_prefix'      # The model ID is 'family/model'
    Field = 'field'             # A (dotted) field of the catalogue entry names the family
    Single = 'single'           # All models are in one family named after the gateway

@dataclass(frozen=True)
class ModelCatalogue:
    """
    Describes how to list a gateway's models, and parses the list into model families.
    """
    path : str                                      # Relative to the server address, e.g. 'v1/models'
    list_key : str = 'data'                         # Key holding the list when the response is an object
    id_field : str = 'id'                           # Field holding the model ID to send
    family_source : FamilySource = FamilySource.IdPrefix
    family_field : str|None = None                  # Dotted path to the family when family_source is Field
    requires_auth : bool = True                     # Send the API key when listing models
    query : Mapping[str, str|int] = field(default_factory=dict)
    required_fields : Mapping[str, Any] = field(default_factory=dict)   # Entries must match all of these values
    required_list_members : Mapping[str, str] = field(default_factory=dict)  # Entries must contain these values in list fields
    excluded_prefixes : tuple[str, ...] = ()        # Skip models whose name (after any vendor prefix) starts with one of these

    def Parse(self, data : Any, gateway_name : str) -> tuple[dict[str, dict[str, str]], list[str]]:
        """
        Group catalogue entries by family as display name -> model ID, and list every model ID.

        Single-family catalogues name their family after the gateway.
        """
        entries = data if isinstance(data, list) else data.get(self.list_key, []) if isinstance(data, dict) else []

        model_cache : dict[str, dict[str, str]] = {}
        all_models : set[str] = set()

        for entry in entries:
            if not isinstance(entry, dict):
                continue

            model_id = entry.get(self.id_field)
            if not isinstance(model_id, str) or not model_id.strip():
                continue

            model_id = model_id.strip()

            if any(entry.get(key) != value for key, value in self.required_fields.items()):
                continue

            if any(not isinstance(entry.get(key), list) or value not in entry[key]
                   for key, value in self.required_list_members.items()):
                continue

            # Match the model name, so 'vendor/veo-3' is excluded by 'veo' whatever the family source
            model_name = model_id.rsplit('/', 1)[-1].lower()
            if model_name.startswith(self.excluded_prefixes):
                continue

            family, display_name = self._get_family_and_name(entry, model_id, gateway_name)

            all_models.add(model_id)
            model_cache.setdefault(family, {})[display_name] = model_id

        return model_cache, sorted(all_models)

    def _get_family_and_name(self, entry : dict, model_id : str, gateway_name : str) -> tuple[str, str]:
        """
        Return the family and display name for a catalogue entry
        """
        match self.family_source:
            case FamilySource.IdPrefix:
                if '/' in model_id:
                    family, name = model_id.split('/', 1)
                    return family, name
                return "Generic", model_id

            case FamilySource.Field:
                family = _get_field(entry, self.family_field) if self.family_field else None
                return (family if isinstance(family, str) and family else "Generic"), model_id

            case FamilySource.Single:
                return gateway_name, model_id

def _get_field(entry : dict, path : str) -> Any:
    """
    Follow a dotted path through nested dictionaries
    """
    value : Any = entry
    for key in path.split('.'):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value
