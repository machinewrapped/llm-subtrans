import unittest
from datetime import timedelta
from typing import TypeVar
from collections.abc import Mapping
from unittest.mock import patch, mock_open

from collections.abc import MutableMapping
from PySubtrans.Options import Options, default_settings, standard_filler_words
from PySubtrans.Instructions import Instructions
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import (
    log_input_expected_error,
    skip_if_debugger_attached,
)
from PySubtrans.SettingsType import SettingsType, SettingType, SettingsError

class TestOptions(LoggedTestCase):
    """Unit tests for the Options class"""

    def setUp(self):
        super().setUp()
        """Set up test fixtures"""
        self.test_options = {
            'provider': 'Test Provider',
            'target_language': 'Spanish',
            'max_batch_size': 25,
            'temperature': 0.5,
            'custom_setting': 'test_value'
        }

    def test_default_initialization(self):
        """Test that Options initializes with default values"""
        
        options = Options()
        
        # Check a selection of stable default options
        test_cases = [
            ('target_language', 'English'),
            ('scene_threshold', 60.0),
            ('max_newlines', 2),
            ('ui_language', 'en'),
            ('filler_words', standard_filler_words),
            ('provider_settings', {}),
        ]
        
        for key, expected in test_cases:
            with self.subTest(key=key):
                result = options.get(key)
                self.assertLoggedEqual(f"options.get('{key}')", expected, result)
        
        # Test boolean defaults
        bool_test_cases = [
            ('project_file', True),
            ('include_original', False),
            ('break_long_lines', True),
            ('normalise_dialog_tags', True),
            ('remove_filler_words', True),
            ('autosave', True),
        ]
        
        for key, expected in bool_test_cases:
            with self.subTest(key=key):
                result = options.get(key)
                self.assertLoggedEqual(f"options.get('{key}')", expected, result)
        
        # Test None values
        none_test_cases = [ 'last_used_path' ]
        
        for key in none_test_cases:
            with self.subTest(key=key):
                result = options.get(key)
                self.assertLoggedIsNone(f"options.get('{key}')", result)

    def test_initialization_with_dict(self):
        """Test Options initialization with a dictionary"""
        
        options = Options(self.test_options)
        
        # Check that custom values override defaults
        custom_test_cases = [
            ('provider', 'Test Provider'),
            ('target_language', 'Spanish'),
            ('max_batch_size', 25),
            ('temperature', 0.5),
            ('custom_setting', 'test_value'),
        ]
        
        for key, expected in custom_test_cases:
            with self.subTest(key=key):
                result = options.get(key)
                self.assertLoggedEqual(f"options.get('{key}')", expected, result)
        
        # Check that defaults are still present for unspecified options
        default_test_cases = [
            ('min_batch_size', 10),
            ('scene_threshold', 60.0),
        ]
        
        for key, expected in default_test_cases:
            with self.subTest(key=key):
                result = options.get(key)
                self.assertLoggedEqual(f"options.get('{key}')", expected, result)

    def test_initialization_with_options_object(self):
        """Test Options initialization with another Options object"""
        
        original = Options(self.test_options)
        copy_options = Options(original)
        
        # Check that values are copied correctly
        copy_test_cases = [
            ('provider', 'Test Provider'),
            ('target_language', 'Spanish'),
            ('max_batch_size', 25),
        ]
        
        for key, expected in copy_test_cases:
            with self.subTest(key=key):
                result = copy_options.get(key)
                self.assertLoggedEqual(f"copy_options.get('{key}')", expected, result)
        
        # Verify it's a deep copy - modifying one doesn't affect the other
        copy_options.set('provider', 'Different Provider')
        
        original_result = original.get('provider')
        copy_result = copy_options.get('provider')
        
        self.assertLoggedEqual("original.get('provider') (original unchanged)", 'Test Provider', original_result)

        self.assertLoggedEqual("copy_options.get('provider') (copy modified)", 'Different Provider', copy_result)

    def test_initialization_with_kwargs(self):
        """Test Options initialization with keyword arguments"""
        
        options = Options(
            provider='Kwargs Provider',
            target_language='French',
            max_batch_size=50
        )
        
        test_cases = [
            ('provider', 'Kwargs Provider'),
            ('target_language', 'French'),
            ('max_batch_size', 50),
        ]
        
        for key, expected in test_cases:
            with self.subTest(key=key):
                result = options.get(key)
                self.assertLoggedEqual(f"options.get('{key}')", expected, result)

    def test_initialization_dict_and_kwargs(self):
        """Test Options initialization with both dict and kwargs (kwargs should override)"""
        
        options = Options(
            self.test_options,
            provider='Kwargs Override Provider',
            max_batch_size=100
        )
        
        # Kwargs should override dict values
        override_test_cases = [
            ('provider', 'Kwargs Override Provider'),
            ('max_batch_size', 100),
        ]
        
        for key, expected in override_test_cases:
            with self.subTest(key=key):
                result = options.get(key)
                self.assertLoggedEqual(f"options.get('{key}')", expected, result)
        
        # Dict values should still be present where not overridden
        preserved_test_cases = [
            ('target_language', 'Spanish'),
            ('temperature', 0.5),
        ]
        
        for key, expected in preserved_test_cases:
            with self.subTest(key=key):
                result = options.get(key)
                self.assertLoggedEqual(f"options.get('{key}')", expected, result)

    def test_none_values_filtered(self):
        """Test that None values in input options are filtered out"""
        
        options_with_none = {
            'provider': 'Test Provider',
            'target_language': None,  # Should be filtered out
            'max_batch_size': 25,
            'custom_setting': None    # Should be filtered out
        }
        
        options = Options(options_with_none)
        
        # None values should be filtered, defaults should remain
        test_cases = [
            ('provider', 'Test Provider'),
            ('target_language', 'English'),
            ('max_batch_size', 25),
        ]
        
        for key, expected in test_cases:
            with self.subTest(key=key):
                result = options.get(key)
                self.assertLoggedEqual(f"options.get('{key}')", expected, result)
        
        # Custom setting with None should not be in options (not in defaults)
        custom_result = options.get('custom_setting')
        self.assertLoggedIsNone("options.get('custom_setting') (None custom setting filtered)", custom_result)

    def test_get_method(self):
        """Test the get method with default values"""
        
        options = Options(self.test_options)
        
        # Test getting existing values
        existing_test_cases = [
            ('provider', 'Test Provider'),
            ('target_language', 'Spanish'),
        ]
        
        for key, expected in existing_test_cases:
            with self.subTest(key=key):
                result = options.get(key)
                self.assertLoggedEqual(f"options.get('{key}')", expected, result)
        
        # Test getting non-existing values with default
        default_result = options.get('non_existing', 'default')
        self.assertLoggedEqual("options.get('non_existing', 'default') (with default)", 'default', default_result)
        
        # Test getting non-existing values without default
        none_result = options.get('non_existing')
        self.assertLoggedIsNone("options.get('non_existing') (no default)", none_result)

    def test_add_method(self):
        """Test the add method"""
        options = Options()
        options.add('new_option', 'new_value')
        
        self.assertEqual(options.get('new_option'), 'new_value')

    def test_set_method(self):
        """Test the set method"""
        options = Options(self.test_options)
        
        # Test setting existing option
        options.set('provider', 'Updated Provider')
        self.assertEqual(options.get('provider'), 'Updated Provider')
        
        # Test setting new option
        options.set('new_option', 'new_value')
        self.assertEqual(options.get('new_option'), 'new_value')

    def test_update_method_with_dict(self):
        """Test the update method with a dictionary"""
        options = Options()
        
        update_dict = {
            'provider': 'Updated Provider',
            'target_language': 'German',
            'new_setting': 'new_value',
            'none_setting': None  # Should be filtered out
        }
        
        options.update(update_dict)
        
        self.assertEqual(options.get('provider'), 'Updated Provider')
        self.assertEqual(options.get('target_language'), 'German')
        self.assertEqual(options.get('new_setting'), 'new_value')
        self.assertIsNone(options.get('none_setting'))

    def test_update_method_with_options(self):
        """Test the update method with another Options object"""
        options1 = Options({'provider': 'Provider 1', 'target_language': 'Spanish'})
        options2 = Options({'provider': 'Provider 2', 'max_batch_size': 50})
        
        options1.update(options2)
        
        # Should have updated values from options2
        self.assertEqual(options1.get('provider'), 'Provider 2')
        self.assertEqual(options1.get('max_batch_size'), 50)
        
        # The update method updates with all options from options2, including defaults
        # So target_language gets updated to English (the default in options2)
        self.assertEqual(options1.get('target_language'), 'English')

    def test_properties(self):
        """Test various properties of Options"""
        options = Options({
            'theme': 'dark',
            'ui_language': 'es',
            'version': '1.0.0',
            'provider': 'Test Provider',
            'provider_settings': {
                'Test Provider': {
                    'model': 'test-model',
                    'api_key': 'test-key'
                }
            },
            'available_providers': ['Provider1', 'Provider2'],
            'target_language': 'French'
        })
        
        # Test basic properties
        self.assertEqual(options.theme, 'dark')
        self.assertEqual(options.ui_language, 'es')
        self.assertEqual(options.version, '1.0.0')
        self.assertEqual(options.provider, 'Test Provider')
        self.assertEqual(options.target_language, 'French')
        self.assertEqual(options.available_providers, ['Provider1', 'Provider2'])
        
        # Test provider settings
        self.assertIsInstance(options.provider_settings, MutableMapping)
        self.assertIsNotNone(options.current_provider_settings)
        if options.current_provider_settings is not None:
            self.assertEqual(options.current_provider_settings.get_str('model'), 'test-model')
        self.assertEqual(options.model, 'test-model')

    def test_provider_setter(self):
        """Test the provider property setter"""
        options = Options()
        options.provider = 'New Provider'
        
        self.assertEqual(options.provider, 'New Provider')
        self.assertEqual(options.get('provider'), 'New Provider')

    def test_current_provider_settings_no_provider(self):
        """Test current_provider_settings when no provider is set"""
        # Create options without provider in defaults and force it to None
        options = Options()
        options.set('provider', None)  # Force to None
        self.assertIsNone(options.current_provider_settings)

    def test_current_provider_settings_missing_provider(self):
        """Test current_provider_settings when provider is not in settings"""
        options = Options({
            'provider': 'Missing Provider',
            'provider_settings': {}
        })
        self.assertIsNone(options.current_provider_settings)

    def test_model_property(self):
        """Test the model property"""
        # Test with no provider
        options = Options()
        self.assertIsNone(options.model)
        
        # Test with provider but no settings
        options = Options({
            'provider': 'Test Provider',
            'provider_settings': {}
        })
        self.assertIsNone(options.model)
        
        # Test with provider and model
        options = Options({
            'provider': 'Test Provider',
            'provider_settings': {
                'Test Provider': {'model': 'test-model'}
            }})
            
        self.assertEqual(options.model, 'test-model')

    def test_get_instructions(self):
        """Test GetInstructions method"""
        options = Options({
            'instructions': 'Test instructions',
            'retry_instructions': 'Test retry instructions'
        })
        
        instructions = options.GetInstructions()
        self.assertIsInstance(instructions, Instructions)

    def test_get_settings(self):
        """Test GetSettings method"""
        options = Options(self.test_options)
        settings = options.GetSettings()
        
        # Should only contain keys that exist in default_options
        self.assertIn('provider', settings)
        self.assertIn('target_language', settings)
        self.assertIn('max_batch_size', settings)
        
        # Should not contain custom keys not in defaults
        self.assertNotIn('custom_setting', settings)
        
        # Values should match
        self.assertEqual(settings['provider'], 'Test Provider')
        self.assertEqual(settings['target_language'], 'Spanish')

    @patch('builtins.open', new_callable=mock_open)
    @patch('os.path.exists')
    def test_load_settings_file_not_exists(self, mock_exists, mock_file):
        """Test LoadSettings when file doesn't exist"""
        mock_exists.return_value = False
        
        options = Options()
        result = options.LoadSettings()
        
        self.assertFalse(result)
        mock_file.assert_not_called()

    @patch('PySubtrans.Helpers.Version.VersionNumberLessThan')
    @patch('json.load')
    @patch('builtins.open', new_callable=mock_open)
    @patch('os.path.exists')
    def test_load_settings_success(self, mock_exists, mock_file, mock_json_load, mock_version):
        """Test successful LoadSettings"""
        mock_exists.return_value = True
        mock_json_load.return_value = {"provider": "Loaded Provider", "target_language": "Italian", "version": "1.0.0"}
        mock_version.return_value = False  # Version is not less than current
        
        options = Options()
        # Override firstrun to False to ensure LoadSettings proceeds
        options.set('firstrun', False)
        result = options.LoadSettings()
        
        self.assertTrue(result)
        self.assertEqual(options.get('provider'), 'Loaded Provider')
        self.assertEqual(options.get('target_language'), 'Italian')

    @patch('builtins.open', new_callable=mock_open)
    @patch('os.makedirs')
    def test_save_settings_success(self, mock_makedirs, mock_file):
        """Test successful SaveSettings"""
        options = Options(self.test_options)
        result = options.SaveSettings()
        
        self.assertTrue(result)
        mock_file.assert_called_once()
        mock_makedirs.assert_called_once()

    def test_build_user_prompt(self):
        """Test BuildUserPrompt method"""
        options = Options({
            'prompt': 'Translate[ to language][ for movie] the following subtitles: [custom_var]',
            'target_language': 'Spanish',
            'movie_name': 'Test Movie',
            'custom_var': 'test_value'
        })
        
        result = options.BuildUserPrompt()
        expected = 'Translate to Spanish for Test Movie the following subtitles: test_value'
        self.assertEqual(result, expected)

    def test_build_user_prompt_empty_values(self):
        """Test BuildUserPrompt with empty/None values"""
        options = Options({
            'prompt': 'Translate[ to language][ for movie] subtitles',
            'target_language': None,
            'movie_name': None
        })
        
        result = options.BuildUserPrompt()
        expected = 'Translate to English subtitles'  # target_language defaults to English
        self.assertEqual(result, expected)

    def test_initialise_instructions_success(self):
        """Test InitialiseInstructions success"""
        mock_instructions = Instructions({
            'prompt': 'Test prompt',
            'instructions': 'Test instructions',
            'retry_instructions': 'Test retry',
            'target_language': None,
            'task_type': None
        })

        options = Options()
        options.InitialiseInstructions(mock_instructions)

        self.assertEqual(options.get('prompt'), 'Test prompt')
        self.assertEqual(options.get('instructions'), 'Test instructions')
        self.assertEqual(options.get('retry_instructions'), 'Test retry')

    def test_initialise_provider_settings(self):
        """Test InitialiseProviderSettings method"""
        options = Options()
        test_settings = SettingsType({
            'model': 'test-model',
            'api_key': 'test-key',
            'temperature': 0.7
        })
        
        options.InitialiseProviderSettings('Test Provider', test_settings)
        
        # Should create provider settings
        self.assertIn('Test Provider', options.provider_settings)
        
        # Should move settings from main options to provider
        provider_settings = options.GetProviderSettings('Test Provider')
        self.assertEqual(provider_settings.get_str('model'), 'test-model')
        self.assertEqual(provider_settings.get_str('api_key'), 'test-key')

    def test_version_update_migration(self):
        """Test _update_version method"""
        options = Options({
            'gpt_model': 'old-model-name',
            'api_key': 'test-key',
            'version': 'v0.9.0'
        })
        
        # Simulate version update
        options._update_version()
        
        # Old gpt_model should be renamed to model and moved to provider settings
        self.assertNotIn('gpt_model', options)

        # The model gets moved to provider settings, not main options
        openai_settings = options.GetProviderSettings('OpenAI')
        if openai_settings:
            self.assertEqual(openai_settings.get('model'), 'old-model-name')
        
        # Version should be updated
        self.assertEqual(options.get('version'), default_settings['version'])


class TestSettingsType(LoggedTestCase):
    """Unit tests for the SettingsType typed getter methods"""

    def setUp(self):
        super().setUp()
        """Set up test fixtures"""
        self.test_settings = SettingsType({
            'bool_true': True,
            'bool_false': False,
            'bool_str_true': 'true',
            'bool_str_false': 'false',
            'int_value': 42,
            'int_str': '123',
            'float_value': 3.14,
            'float_str': '2.718',
            'str_value': 'hello world',
            'str_int': 123,
            'timedelta_seconds': 30.5,
            'str_list': ['apple', 'banana', 'cherry'],
            'mixed_list': ['1', 'two', 'True'],
            'nested_dict': SettingsType({
                'inner_str': 'nested_value',
                'inner_int': 100,
                'inner_bool': True
            }),
            'none_value': None
        })

    def test_get_bool(self):
        """Test SettingsType.get_bool method"""
        
        test_cases = [
            ('bool_true', True),
            ('bool_false', False),
            ('bool_str_true', True),
            ('bool_str_false', False),
            ('missing_key', False),
            ('none_value', False),
        ]
        
        for key, expected in test_cases:
            with self.subTest(key=key):
                result = self.test_settings.get_bool(key)
                self.assertLoggedEqual(f"get_bool('{key}')", expected, result)
        
        # Test custom default
        result = self.test_settings.get_bool('missing_key', True)
        self.assertLoggedTrue("get_bool with custom default True", result)

    def test_get_int(self):
        """Test SettingsType.get_int method"""
        
        test_cases = [
            ('int_value', 42),
            ('int_str', 123),
            ('missing_key', None),
            ('none_value', None),
        ]
        
        for key, expected in test_cases:
            with self.subTest(key=key):
                result = self.test_settings.get_int(key)
                self.assertLoggedEqual(f"get_int('{key}')", expected, result)
        
        # Test custom default
        result = self.test_settings.get_int('missing_key', 999)
        self.assertLoggedEqual("get_int with custom default", 999, result)

    def test_get_float(self):
        """Test SettingsType.get_float method"""
        
        test_cases = [
            ('float_value', 3.14),
            ('float_str', 2.718),
            ('int_value', 42.0),
            ('missing_key', None),
            ('none_value', None),
        ]
        
        for key, expected in test_cases:
            with self.subTest(key=key):
                result = self.test_settings.get_float(key)
                self.assertLoggedEqual(f"get_float('{key}')", expected, result)
        
        # Test custom default
        result = self.test_settings.get_float('missing_key', 1.23)
        self.assertLoggedEqual("get_float with custom default", 1.23, result)

    def test_get_str(self):
        """Test SettingsType.get_str method"""
        
        test_cases = [
            ('str_value', 'hello world'),
            ('str_int', '123'),
            ('missing_key', None),
            ('none_value', None),
        ]
        
        for key, expected in test_cases:
            with self.subTest(key=key):
                result = self.test_settings.get_str(key)
                self.assertLoggedEqual(f"get_str('{key}')", expected, result)
        
        # Test custom default
        result = self.test_settings.get_str('missing_key', 'default_string')
        self.assertLoggedEqual("get_str with custom default", 'default_string', result)

    def test_get_timedelta(self):
        """Test SettingsType.get_timedelta method"""
        
        default_td = timedelta(minutes=5)
        
        # Test with valid seconds value
        result = self.test_settings.get_timedelta('timedelta_seconds', default_td)
        expected = timedelta(seconds=30.5)
        self.assertLoggedEqual("get_timedelta with float seconds", expected, result)
        
        # Test with missing key
        result = self.test_settings.get_timedelta('missing_key', default_td)
        self.assertLoggedEqual("get_timedelta with missing key", default_td, result)

    def test_get_str_list(self):
        """Test SettingsType.get_str_list method"""
        
        test_cases = [
            ('str_list', ['apple', 'banana', 'cherry']),
            ('mixed_list', ['1', 'two', 'True']),
            ('missing_key', []),
        ]
        
        for key, expected in test_cases:
            with self.subTest(key=key):
                result = self.test_settings.get_str_list(key)
                self.assertLoggedEqual(f"get_str_list('{key}')", expected, result)
        
        # Test custom default
        custom_default = ['default1', 'default2']
        result = self.test_settings.get_str_list('missing_key', custom_default)
        self.assertLoggedSequenceEqual("get_str_list with custom default", custom_default, result)

    def test_get_list(self):
        """Test SettingsType.get_list method"""
        
        test_cases = [
            ('str_list', ['apple', 'banana', 'cherry']),
            ('mixed_list', ['1', 'two', 'True']),
            ('missing_key', []),
        ]
        
        for key, expected in test_cases:
            with self.subTest(key=key):
                result = self.test_settings.get_list(key)
                self.assertLoggedEqual(f"get_list('{key}')", expected, result)
        
        # Test custom default
        custom_default = ['default', 123, True]
        result = self.test_settings.get_list('missing_key', custom_default)
        self.assertLoggedEqual("get_list with custom default", custom_default, result)

    def test_get_dict(self):
        """Test SettingsType.get_dict method and nested dict functionality"""
        
        # Test getting nested dict
        result = self.test_settings.get_dict('nested_dict')
        expected = {'inner_str': 'nested_value', 'inner_int': 100, 'inner_bool': True}
        self.assertLoggedEqual("get_dict('nested_dict')", expected, result)
        
        # Test missing key returns empty dict
        result = self.test_settings.get_dict('missing_key')
        self.assertLoggedEqual("get_dict with missing key", {}, result)
        
        # Test custom default
        custom_default = SettingsType({'default_key': 'default_value'})
        result = self.test_settings.get_dict('missing_key', custom_default)
        self.assertLoggedEqual("get_dict with custom default", custom_default, result)
        
        # Test that get_dict returns a mutable reference to nested dictionaries
        nested_dict = self.test_settings.get_dict('nested_dict')
        
        # Modifying the returned dict should update the parent
        nested_dict['new_key'] = 'new_value'
        
        # Verify the parent was updated
        updated_nested = self.test_settings.get_dict('nested_dict')
        self.assertIn('new_key', updated_nested)
        self.assertLoggedEqual("nested dict update propagated", 'new_value', updated_nested['new_key'])
        
        # Also verify through direct access
        direct_nested = self.test_settings['nested_dict']
        if isinstance(direct_nested, SettingsType):
            self.assertIn('new_key', direct_nested)
            self.assertLoggedEqual("nested update visible in direct access", 'new_value', direct_nested['new_key'])

    def test_provider_settings_nested_updates(self):
        """Test that provider_settings properly handles nested updates"""
        
        # Create Options with provider settings
        options = Options({
            'provider': 'Test Provider',
            'provider_settings': {
                'Test Provider': SettingsType({
                    'model': 'test-model',
                    'temperature': 0.7,
                    'api_key': 'test-key'
                }),
                'Other Provider': SettingsType({
                    'model': 'other-model',
                    'temperature': 0.5
                })
            }
        })
        
        # Test that provider_settings returns a mutable mapping
        provider_settings = options.provider_settings
        self.assertLoggedIsInstance("provider_settings is MutableMapping", provider_settings, MutableMapping)

        # Test accessing existing provider settings
        test_provider_settings = provider_settings['Test Provider']
        self.assertLoggedIsInstance("provider settings is SettingsType", test_provider_settings, SettingsType)
        
        # Test accessing values through typed getters
        model = test_provider_settings.get_str('model')
        temperature = test_provider_settings.get_float('temperature')
        api_key = test_provider_settings.get_str('api_key')
        
        self.assertLoggedEqual("provider model", 'test-model', model)
        self.assertLoggedEqual("provider temperature", 0.7, temperature)
        self.assertLoggedEqual("provider api_key", 'test-key', api_key)
        
        # Test modifying provider settings updates the parent Options
        test_provider_settings['new_setting'] = 'new_value'
        
        # Verify the change is reflected in the main options
        updated_provider_settings = options.provider_settings['Test Provider']
        self.assertIn('new_setting', updated_provider_settings)
        self.assertLoggedEqual("nested provider update propagated", 'new_value', updated_provider_settings['new_setting'])
        
        # Test adding a new provider through the mutable mapping
        new_provider_settings = SettingsType({
            'model': 'new-provider-model',
            'temperature': 0.8
        })
        provider_settings['New Provider'] = new_provider_settings
        
        # Verify the new provider is accessible
        self.assertIn('New Provider', options.provider_settings)
        new_settings = options.provider_settings['New Provider']
        self.assertLoggedEqual("new provider model", 'new-provider-model', new_settings.get_str('model'))
        
        # Test current_provider_settings property
        current_settings = options.current_provider_settings
        self.assertLoggedIsNotNone("current provider settings", current_settings)
        if current_settings:
            current_model = current_settings.get_str('model')
            self.assertLoggedEqual("current provider model", 'test-model', current_model)
            
            # Test that modifying current_provider_settings updates the main options
            current_settings['current_test'] = 'current_value'
            
            # Verify through provider_settings access
            provider : str|None = options.provider
            self.assertIsNotNone(provider)
            self.assertIsNotNone(options.provider_settings)
            if provider is not None:
                updated_current : SettingsType = options.provider_settings[provider]
                self.assertIn('current_test', updated_current)
                self.assertLoggedEqual("current provider update propagated", 'current_value', updated_current['current_test'])

class TestSettingsHelpers(LoggedTestCase):
    """Unit tests for Settings helper functions"""

    def setUp(self):
        super().setUp()
        """Set up test fixtures with known values"""
        self.test_dict_settings = SettingsType({
            'bool_true': True,
            'bool_false': False,
            'bool_str_true': 'true',
            'bool_str_false': 'false',
            'bool_str_invalid': 'maybe',
            'int_value': 42,
            'int_str': '123',
            'int_float': 45.0,
            'int_invalid': 'not_a_number',
            'float_value': 3.14,
            'float_int': 42,
            'float_str': '2.718',
            'float_invalid': 'not_a_float',
            'str_value': 'hello world',
            'str_int': 123,
            'str_bool': True,
            'str_list': ['item1', 'item2'],
            'list_value': ['apple', 'banana', 'cherry'],
            'list_str_comma': 'red,green,blue',
            'list_str_semicolon': 'cat;dog;bird',
            'list_invalid': 42,
            'timedelta_seconds': 30.5,
            'timedelta_str': '15,000',
            'timedelta_int': 60,
            'timedelta_invalid': 'invalid',
        })
        
        self.test_options_obj = Options(self.test_dict_settings)

    def test_get_bool_setting(self):
        """Test GetBoolSetting with various input types"""
        
        test_cases = [
            ('bool_true', True),
            ('bool_false', False),
            ('bool_str_true', True),
            ('bool_str_false', False),
            ('missing_key', False),
        ]
        
        for key, expected in test_cases:
            with self.subTest(key=key):
                result = self.test_dict_settings.get_bool(key)
                self.assertLoggedEqual(f"dict['{key}']", expected, result)
                result_opts = self.test_options_obj.get_bool(key)
                self.assertLoggedEqual(f"Options['{key}']", expected, result_opts)
        
        # Test custom default
        result = self.test_dict_settings.get_bool('missing_key', True)
        self.assertLoggedTrue("missing key with default True", result)
        
        # Test None value
        settings_with_none = {'none_value': None}
        settings_with_none_obj = SettingsType(settings_with_none)
        result = settings_with_none_obj.get_bool('none_value')
        self.assertLoggedFalse("None value", result)

    @skip_if_debugger_attached
    def test_get_bool_setting_errors(self):
        """Test GetBoolSetting error cases"""
        
        error_case_keys = ['bool_str_invalid', 'int_value']
        for key in error_case_keys:
            with self.subTest(key=key):
                with self.assertRaises(SettingsError) as cm:
                    self.test_dict_settings.get_bool(key)
                log_input_expected_error(key, SettingsError, cm.exception)

    def test_get_int_setting(self):
        """Test GetIntSetting with various input types"""
        
        test_cases = [
            ('int_value', 42),
            ('int_str', 123),
            ('int_float', 45),
            ('missing_key', None),
        ]
        
        for key, expected in test_cases:
            with self.subTest(key=key):
                result = self.test_dict_settings.get_int(key)
                self.assertLoggedEqual(key, expected, result)
        
        # Test None handling
        settings_with_none = SettingsType({'none_value': None})
        result = settings_with_none.get_int('none_value')
        self.assertLoggedIsNone("None value", result)

    @skip_if_debugger_attached
    def test_get_int_setting_errors(self):
        """Test GetIntSetting error cases"""
        
        with self.assertRaises(SettingsError) as cm:
            self.test_dict_settings.get_int('int_invalid')
        log_input_expected_error('int_invalid', SettingsError, cm.exception)

    def test_get_float_setting(self):
        """Test GetFloatSetting with various input types"""
        
        test_cases = [
            ('float_value', 3.14),
            ('float_int', 42.0),
            ('float_str', 2.718),
        ]
        
        for key, expected in test_cases:
            with self.subTest(key=key):
                result = self.test_dict_settings.get_float(key)
                self.assertLoggedEqual(key, expected, result)
        
        # Test None handling
        result = self.test_dict_settings.get_float('missing_key')
        self.assertLoggedIsNone("missing key", result)

    @skip_if_debugger_attached
    def test_get_float_setting_errors(self):
        """Test GetFloatSetting error cases"""
        
        with self.assertRaises(SettingsError) as cm:
            self.test_dict_settings.get_float('float_invalid')
        log_input_expected_error('float_invalid', SettingsError, cm.exception)

    def test_get_str_setting(self):
        """Test GetStrSetting with various input types"""
        
        test_cases = [
            ('str_value', 'hello world'),
            ('str_int', '123'),
            ('str_bool', 'True'),
            ('str_list', 'item1, item2'),
        ]
        
        for key, expected in test_cases:
            with self.subTest(key=key):
                result = self.test_dict_settings.get_str(key)
                self.assertLoggedEqual(key, expected, result)
        
        # Test None handling
        result = self.test_dict_settings.get_str('missing_key')
        self.assertLoggedIsNone("missing key", result)

    def test_get_list_setting(self):
        """Test GetListSetting with various input types"""
        
        test_cases = [
            ('list_value', ['apple', 'banana', 'cherry']),
            ('list_str_comma', ['red', 'green', 'blue']),
            ('list_str_semicolon', ['cat', 'dog', 'bird']),
        ]
        
        for key, expected in test_cases:
            with self.subTest(key=key):
                result = self.test_dict_settings.get_list(key)
                self.assertLoggedEqual(key, expected, result)
        
        # Test missing key returns empty list
        result = self.test_dict_settings.get_list('missing_key')
        self.assertLoggedEqual("missing key", [], result)
        
    @skip_if_debugger_attached
    def test_get_list_setting_errors(self):
        """Test GetListSetting error cases"""
        
        with self.assertRaises(SettingsError) as cm:
            self.test_dict_settings.get_list('list_invalid')
        log_input_expected_error('list_invalid', SettingsError, cm.exception)

    def test_get_string_list_setting(self):
        """Test GetStringListSetting function"""
        
        # Test with valid string list
        result = self.test_dict_settings.get_str_list('list_value')
        expected = ['apple', 'banana', 'cherry']
        self.assertLoggedEqual("valid string list", expected, result)
        
        # Test with mixed types (should convert to strings)
        mixed_settings = {'mixed_list': [1, 'two', True, None]}
        mixed_settings_obj = SettingsType(mixed_settings)
        result = mixed_settings_obj.get_str_list('mixed_list')
        expected = ['1', 'two', 'True']
        self.assertLoggedEqual("mixed types", expected, result)

    def test_get_timedelta_setting(self):
        """Test GetTimeDeltaSetting function"""
        
        test_cases = [
            ('timedelta_seconds', timedelta(seconds=30.5)),
            ('timedelta_str', timedelta(seconds=15.0)),
            ('timedelta_int', timedelta(seconds=60)),
        ]
        
        for key, expected in test_cases:
            with self.subTest(key=key):
                default = timedelta(minutes=1)  # Use a different default to distinguish from expected
                result = self.test_dict_settings.get_timedelta(key, default)
                self.assertLoggedEqual(key, expected, result)
        
        # Test default value
        default = timedelta(minutes=5)
        result = self.test_dict_settings.get_timedelta('missing_key', default)
        self.assertLoggedEqual("missing key with default", default, result)

    @skip_if_debugger_attached
    def test_get_timedelta_setting_errors(self):
        """Test GetTimeDeltaSetting error cases"""
        
        with self.assertRaises(SettingsError) as cm:
            self.test_dict_settings.get_timedelta('timedelta_invalid', timedelta(seconds=1))
        log_input_expected_error('timedelta_invalid', SettingsError, cm.exception)

    def test_get_optional_setting(self):
        """Test get_optional_setting function"""
        
        test_cases = [
            ('bool_true', bool, True),
            ('int_value', int, 42),
            ('float_value', float, 3.14),
            ('str_value', str, 'hello world'),
            ('list_value', list, ['apple', 'banana', 'cherry']),
        ]
        
        for key, setting_type, expected in test_cases:
            with self.subTest(key=key):
                result = get_optional_setting(self.test_dict_settings, key, setting_type)
                self.assertLoggedEqual(key, expected, result)
        
        # Test missing key returns None
        result = get_optional_setting(self.test_dict_settings, 'missing_key', str)
        self.assertLoggedIsNone("missing key", result)
        
        # Test with Options object
        result = get_optional_setting(self.test_options_obj, 'bool_true', bool)
        self.assertLoggedTrue("Options object", result or False)

    @skip_if_debugger_attached
    def test_get_optional_setting_errors(self):
        """Test get_optional_setting error cases"""
        
        with self.assertRaises(SettingsError) as cm:
            get_optional_setting(self.test_dict_settings, 'bool_str_invalid', bool)
        log_input_expected_error('bool_str_invalid', SettingsError, cm.exception)

    def test_validate_setting_type(self):
        """Test validate_setting_type function"""
        
        valid_cases = [
            ('bool_true', bool, True),
            ('int_value', int, True),
            ('str_value', str, True),
        ]
        
        for key, setting_type, expected in valid_cases:
            with self.subTest(key=key):
                result = validate_setting_type(self.test_dict_settings, key, setting_type)
                self.assertLoggedEqual(f"'{key}' as {setting_type.__name__}", expected, result)
        
    @skip_if_debugger_attached
    def test_validate_setting_type_errors(self):
        """Test validate_setting_type error cases"""
        
        # Test missing optional setting
        result = validate_setting_type(self.test_dict_settings, 'missing_key', str, required=False)
        self.assertLoggedTrue("missing optional setting", result)
        
        # Test invalid type
        result = validate_setting_type(self.test_dict_settings, 'bool_str_invalid', bool)
        self.assertLoggedFalse("invalid type conversion", result)

        # Test required missing setting
        with self.assertRaises(SettingsError) as cm:
            validate_setting_type(self.test_dict_settings, 'missing_key', str, required=True)
        log_input_expected_error('missing_key', SettingsError, cm.exception)

T = TypeVar('T')

def get_optional_setting(settings: SettingsType|Mapping[str, SettingType], key: str, setting_type: type[T]) -> T | None:
    """
    Safely retrieve an optional setting that may not be present.
    """
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
        return settings.get_list(key)  # type: ignore
    else:
        # For other types, try direct conversion
        if isinstance(value, setting_type):
            return value
        else:
            raise SettingsError(f"Cannot convert setting '{key}' of type {type(value).__name__} to {setting_type.__name__}")


def validate_setting_type(settings: SettingsType|Mapping[str, SettingType], key: str, expected_type: type[T], required: bool = False) -> bool:
    """
    Validate that a setting can be converted to the expected type without actually converting it.
    
    Raises:
        SettingsError: If validation fails
    """
    if key not in settings:
        if required:
            raise SettingsError(f"Required setting '{key}' is missing")
        return True
    
    try:
        get_optional_setting(settings, key, expected_type)
        return True
    except SettingsError:
        return False

if __name__ == '__main__':
    unittest.main()
