from __future__ import annotations
from collections.abc import Mapping, MutableMapping
from copy import deepcopy
import json
import logging
import os
from typing import Any
import dotenv

from PySubtitle.Helpers.Version import VersionNumberLessThan
from PySubtitle.Instructions import Instructions, LoadInstructions, default_user_prompt
from PySubtitle.Helpers.Localization import _
from PySubtitle.Helpers.Resources import config_dir, old_config_dir
from PySubtitle.Helpers.Text import standard_filler_words
from PySubtitle.ProviderSettingsView import ProviderSettingsView
from PySubtitle.SettingsType import SettingType, SettingsType
from PySubtitle.version import __version__

MULTILINE_OPTION = 'multiline'

settings_path = os.path.join(config_dir, 'settings.json')

# Load environment variables from .env file
dotenv.load_dotenv()

def env_bool(key : str, default : bool = False) -> bool:
    var = os.getenv(key, default)
    return True if var and str(var).lower() in ('true', 'yes', '1') else False

def env_int(key : str, default : int|None = None) -> int|None:
    value = os.getenv(key, default)
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return int(value)

def env_float(key : str, default : float|None = None) -> float|None:
    value = os.getenv(key, default)
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return float(value)

def env_str(key : str, default : str|None = None) -> str|None:
    value = os.getenv(key, default)
    return str(value) if value is not None else None

default_settings = {
    'version': __version__,
    'provider': env_str('PROVIDER', None),
    'provider_settings': SettingsType({}),
    'prompt': env_str('PROMPT', default_user_prompt),
    'instruction_file': env_str('INSTRUCTION_FILE', "instructions.txt"),
    'target_language': env_str('TARGET_LANGUAGE', 'English'),
    'include_original': env_bool('INCLUDE_ORIGINAL', False),
    'add_right_to_left_markers': env_bool('add_right_to_left_markers', False),
    'scene_threshold': env_float('SCENE_THRESHOLD', 30.0),
    'min_batch_size': env_int('MIN_BATCH_SIZE', 10),
    'max_batch_size': env_int('MAX_BATCH_SIZE', 30),
    'max_context_summaries': env_int('MAX_CONTEXT_SUMMARIES', 10),
    'max_characters': env_int('MAX_CHARACTERS', 120),
    'max_newlines': env_int('MAX_NEWLINES', 2),
    'max_single_line_length': env_int('MAX_SINGLE_LINE_LENGTH', 44),
    'min_single_line_length': env_int('MIN_SINGLE_LINE_LENGTH', 8),
    'postprocess_translation': env_bool('POSTPROCESS_TRANSLATION', False),
    'preprocess_subtitles': env_bool('PREPROCESS_SUBTITLES', False),
    'save_preprocessed_subtitles': env_bool('SAVE_PREPROCESSED_SUBTITLES', False),
    'break_long_lines': env_bool('BREAK_LONG_LINES', True),
    'break_dialog_on_one_line': env_bool('break_dialog_on_one_line', True),
    'max_line_duration': env_float('MAX_LINE_DURATION', 4.0),
    'min_line_duration': env_float('MIN_LINE_DURATION', 0.8),
    'merge_line_duration': env_float('MERGE_LINE_DURATION', 0.0),
    'min_split_chars': env_int('MIN_SPLIT_CHARS', 3),
    'normalise_dialog_tags': env_bool('NORMALISE_DIALOG_TAGS', True),
    'remove_filler_words': env_bool('REMOVE_FILLER_WORDS', True),
    'filler_words': standard_filler_words,
    'substitution_mode': env_str('SUBSTITUTION_MODE', "Auto"),
    'whitespaces_to_newline' : env_bool('WHITESPACES_TO_NEWLINE', False),
    'full_width_punctuation': env_bool('FULL_WIDTH_PUNCTUATION', False),
    'convert_wide_dashes': env_bool('CONVERT_WIDE_DASHES', True),
    'retry_on_error': env_bool('RETRY_ON_ERROR', True),
    # 'autosplit_incomplete': env_bool('AUTOSPLIT_INCOMPLETE', True),
    'max_lines': env_int('MAX_LINES', None),
    'max_threads': env_int('MAX_THREADS', 4),
    'max_retries': env_int('MAX_RETRIES', 1),
    'max_summary_length': env_int('MAX_SUMMARY_LENGTH', 240),
    'backoff_time': env_float('BACKOFF_TIME', 3.0),
    'project_file' : env_bool('PROJECT_FILE', True),
    'autosave': env_bool('AUTOSAVE', True),
    'preview' : False,
    'retranslate' : False,
    'reparse' : False,
    'reload' : False,
    'last_used_path': None,
    'stop_on_error' : env_bool('STOP_ON_ERROR'),
    'write_backup' : env_bool('WRITE_BACKUP_FILE', True),
    'theme' : env_str('THEME', 'default'),
    'ui_language': env_str('UI_LANGUAGE', 'en'),
    'firstrun' : True
}

def serialize(value : Any) -> Any:
    return value.serialize() if hasattr(value, 'serialize') else value

class Options(SettingsType):
    def __init__(self, settings : SettingsType|Mapping[str, SettingType]|None = None, **kwargs : SettingType):
        """ Initialise the Options object with default options and any provided options. """
        super().__init__()
        self.is_project_options : bool = False

        self.update(deepcopy(default_settings))

        # Convert plain dict to SettingsType for type safety
        settings = SettingsType(settings)

        if settings:
            # Remove None values from options and merge with defaults
            filtered_settings = {k: deepcopy(v) for k, v in settings.items() if v is not None}
            self.update(filtered_settings)

        # Apply any explicit parameters
        self.update(kwargs)

    # items() inherits from dict - no need to override

    @property
    def theme(self) -> str:
        return self.get_str('theme') or ''
    
    @property
    def ui_language(self) -> str:
        return self.get_str('ui_language') or 'en'

    @property
    def version(self) -> str:
        return self.get_str('version') or ''

    @property
    def provider(self) -> str|None:
        """ the name of the translation provider """
        return self.get_str('provider')

    @provider.setter
    def provider(self, value: str):
        self['provider'] = value

    @property
    def provider_settings(self) -> MutableMapping[str, SettingsType]:
        """ Type-safe mutable view of provider settings """
        return ProviderSettingsView(self, 'provider_settings')

    @property
    def current_provider_settings(self) -> SettingsType|None:
        if not self.provider or not self.provider in self.provider_settings:
            return None

        return self.provider_settings.get(self.provider)

    @property
    def available_providers(self) -> list[str]:
        return self.get_list('available_providers', [])

    @property
    def model(self) -> str|None:
        if not self.provider:
            return None

        current_provider_settings = self.current_provider_settings
        if not current_provider_settings:
            return None

        return str(current_provider_settings.get('model'))

    @property
    def target_language(self) -> str:
        return self.get_str('target_language') or str(default_settings['target_language'])

    @property
    def project_file(self) -> bool:
        return self.get_bool('project_file', True)

    def GetProviderSettings(self, provider : str) -> SettingsType:
        """ Get the settings for a specific provider """
        if not provider:
            return SettingsType()

        return deepcopy(self.provider_settings.get(provider, SettingsType()))

    def GetInstructions(self) -> Instructions:
        """ Construct an Instructions object from the settings """
        return Instructions(dict(self))

    def GetSettings(self) -> SettingsType:
        """
        Get a copy of the settings dictionary with only the default keys included
        """
        keys = self.keys() & default_settings.keys()
        settings = SettingsType({ key: deepcopy(dict.get(self, key)) for key in keys })
        return settings

    def LoadSettings(self) -> bool:
        """
        Load the settings from a JSON file
        """
        if not os.path.exists(settings_path):
            return False

        try:
            with open(settings_path, "r", encoding="utf-8") as settings_file:
                settings = json.load(settings_file)

            if not settings:
                return False

            if not self:
                self.update(deepcopy(default_settings))

            self.update(settings)

            saved_version : str = str(settings.get('version'))
            current_version : str = str(default_settings['version'])
            if VersionNumberLessThan(saved_version, current_version):
                self._update_version()

            return True

        except Exception as e:
            logging.debug("Error loading settings from {}: {}".format(settings_path, e))
            logging.error(_("Error loading settings from {}").format(settings_path))
            return False

    def SaveSettings(self) -> bool:
        """
        Save the settings to a JSON file
        """
        try:
            settings : SettingsType = self.GetSettings()

            if not settings:
                return False

            save_dict = { key : value for key, value in settings.items() if value != default_settings.get(key) }

            if save_dict:
                os.makedirs(config_dir, exist_ok=True)

                save_dict['version'] = str(default_settings['version'])

                with open(settings_path, "w", encoding="utf-8") as settings_file:
                    json.dump(save_dict, settings_file, ensure_ascii=False, indent=4, sort_keys=True, default=serialize)

            return True

        except Exception as e:
            logging.debug("Error saving settings to {}: {}".format(settings_path, e))
            logging.error(_("Error saving settings to {}").format(settings_path))
            return False
        
    def MigrateSettings(self) -> bool:
        """
        Migrate settings from the old config directory to the new one
        """
        if os.path.exists(settings_path):
            return False
        
        old_settings_path = os.path.join(old_config_dir, 'settings.json')
        if not os.path.exists(old_settings_path):
            return False

        try:
            if not os.path.exists(config_dir):
                # Rename the old config directory to the new one
                os.rename(old_config_dir, config_dir)
                logging.info("Settings migrated to new location")
            else:
                os.rename(old_settings_path, settings_path)
                logging.info("Settings file migrated to new location")

                old_custom_instructions_path = os.path.join(old_config_dir, 'instructions')
                if os.path.exists(old_custom_instructions_path):
                    new_custom_instructions_path = os.path.join(config_dir, 'instructions')
                    if not os.path.exists(new_custom_instructions_path):
                        os.rename(old_custom_instructions_path, new_custom_instructions_path)
                        logging.info("Custom instructions migrated to new location")                
                
            return True

        except Exception as e:
            logging.debug(f"Error migrating settings from {old_config_dir} to {config_dir}: {e}")
            logging.error(_("Error migrating settings from {} to {}. You can copy the files manually and restart the application.").format(old_config_dir, config_dir))
            return False

    def BuildUserPrompt(self) -> str:
        """
        Generate the user prompt to use for requesting translations
        """
        target_language = self.get_str('target_language') or ''
        movie_name = self.get_str('movie_name') or ''
        prompt = self.get_str('prompt') or default_user_prompt
        prompt = prompt.replace('[ to language]', f" to {target_language}" if target_language else "")
        prompt = prompt.replace('[ for movie]', f" for {movie_name}" if movie_name else "")

        for k,v in self.items():
            if v:
                prompt = prompt.replace(f"[{k}]", str(v))

        return prompt.strip()

    def InitialiseInstructions(self):
        """
        Load options from instructions file if specified
        """
        instruction_file = self.get_str('instruction_file') or ''
        if instruction_file:
            try:
                instructions = LoadInstructions(instruction_file)
                self['prompt'] = instructions.prompt
                self['instructions'] = instructions.instructions
                self['retry_instructions'] = instructions.retry_instructions

            except Exception as e:
                logging.error(_("Unable to load instructions from {}: {}").format(instruction_file, e))

    def InitialiseProviderSettings(self, provider : str, settings : SettingsType) -> None:
        """
        Create or update the settings for a provider
        """
        if provider not in self.provider_settings:
            self.provider_settings[provider] = SettingsType(deepcopy(settings))

        self.MoveSettingsToProvider(provider, list(settings.keys()))

    def MoveSettingsToProvider(self, provider : str, keys : list[str]) -> None:
        """
        Move settings from the main options to a provider's settings
        """
        if provider not in self.provider_settings:
            self.provider_settings[provider] = SettingsType()

        settings_to_move : dict[str,SettingType] = {key: self.pop(key) for key in keys if key in self}
        if settings_to_move:
            provider_settings = self.provider_settings[provider]
            # provider_settings is always SettingsType, so we can update it directly
            provider_settings.update(settings_to_move)

    def _update_version(self):
        """
        Update settings from older versions of the application
        """
        if 'gpt_model' in self:
            self['model'] = self['gpt_model']
            del self['gpt_model']

        if not self.provider_settings:
            self['provider_settings'] = {'OpenAI': {}} if self.get_str('api_key') else {}
            self.MoveSettingsToProvider('OpenAI', ['api_key', 'api_base', 'model', 'free_plan', 'max_instruct_tokens', 'temperature', 'rate_limit'])

        latest_version  : str = str(default_settings['version'])

        self['version'] = latest_version


