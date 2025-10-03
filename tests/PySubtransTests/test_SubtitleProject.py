import os
import tempfile
import unittest

from PySubtrans.Helpers.TestCases import SubtitleTestCase
from PySubtrans.Helpers.Tests import (
    log_input_expected_result,
    log_test_name,
    skip_if_debugger_attached,
)
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleBatcher import SubtitleBatcher
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.SubtitleScene import SubtitleScene
from PySubtrans.Subtitles import Subtitles
from ..TestData.chinese_dinner import chinese_dinner_data


class SubtitleProjectTests(SubtitleTestCase):
    """Test suite for SubtitleProject class functionality"""

    def __init__(self, methodName):
        super().__init__(methodName, custom_options={
            'max_batch_size': 100,
        })

    def setUp(self):
        """Set up test fixtures"""
        log_test_name(self._testMethodName)

        self.temp_dir = tempfile.mkdtemp()
        self.test_srt_file = os.path.join(self.temp_dir, "test.srt")
        self.test_project_file = os.path.join(self.temp_dir, "test.subtrans")

        # Write test SRT content
        with open(self.test_srt_file, 'w', encoding='utf-8') as f:
            original_content = chinese_dinner_data.get_str('original') or ''
            f.write(original_content)

    def tearDown(self):
        """Clean up test fixtures"""
        try:
            if os.path.exists(self.test_srt_file):
                os.remove(self.test_srt_file)
            if os.path.exists(self.test_project_file):
                os.remove(self.test_project_file)
            os.rmdir(self.temp_dir)
        except Exception:
            pass

    def test_default_initialization(self):
        """Test SubtitleProject initializes with default settings"""

        project = SubtitleProject()

        # Test basic initialization
        log_input_expected_result("project.subtitles exists", True, project.subtitles is not None)
        self.assertIsNotNone(project.subtitles)

        log_input_expected_result("project.subtitles type", Subtitles, type(project.subtitles))
        self.assertIsInstance(project.subtitles, Subtitles)

        # Test that default project settings are applied
        default_settings = SubtitleProject.DEFAULT_PROJECT_SETTINGS
        for key in default_settings.keys():
            if default_settings[key] is None:
                continue
            actual_value = project.subtitles.settings.get(key)
            expected_value = default_settings[key]
            log_input_expected_result(f"default setting '{key}'", expected_value, actual_value)
            self.assertEqual(actual_value, expected_value)

        # Test project-specific properties
        log_input_expected_result("project.projectfile", None, project.projectfile)
        self.assertIsNone(project.projectfile)

        log_input_expected_result("project.existing_project", False, project.existing_project)
        self.assertFalse(project.existing_project)

        log_input_expected_result("project.needs_writing", False, project.needs_writing)
        self.assertFalse(project.needs_writing)

        log_input_expected_result("project.use_project_file", False, project.use_project_file)
        self.assertFalse(project.use_project_file)

    def test_persistent_initialization(self):
        """Test SubtitleProject initialization with persistent=True"""

        project = SubtitleProject(persistent=True)

        log_input_expected_result("persistent project.use_project_file", True, project.use_project_file)
        self.assertTrue(project.use_project_file)

    def test_update_project_settings_normal(self):
        """Test UpdateProjectSettings with normal settings"""

        project = SubtitleProject()

        # Test updating with normal settings - mix valid and invalid to test filtering
        normal_settings = SettingsType({
            'target_language': 'Spanish',        # Valid project setting
            'movie_name': 'Test Movie',          # Valid project setting
            'description': 'Test description',   # Valid project setting
            'names': ['Character1', 'Character2'], # Valid project setting
            'provider': 'Test Provider',         # Valid project setting
            'invalid_setting': 'should_be_filtered',  # NOT in DEFAULT_PROJECT_SETTINGS
            'scene_threshold': 45.0,             # Valid option but NOT project setting
        })

        project.UpdateProjectSettings(normal_settings)

        # Verify valid settings were applied
        test_cases = [
            ('target_language', 'Spanish'),
            ('movie_name', 'Test Movie'),
            ('description', 'Test description'),
            ('provider', 'Test Provider')
        ]

        for key, expected in test_cases:
            actual = project.subtitles.settings.get(key)
            log_input_expected_result(f"valid setting '{key}'", expected, actual)
            self.assertEqual(actual, expected, f"Valid project setting '{key}' should be stored")

        # Test names were parsed correctly
        names = project.subtitles.settings.get_str_list('names')
        expected_names = ['Character1', 'Character2']
        log_input_expected_result(names, expected_names, names)
        self.assertEqual(names, expected_names)

        # CRITICAL: Test that invalid settings were filtered out
        invalid_setting = project.subtitles.settings.get('invalid_setting')
        log_input_expected_result(invalid_setting, None, invalid_setting)
        self.assertIsNone(invalid_setting, "Invalid settings should be filtered out by UpdateProjectSettings")

        scene_threshold = project.subtitles.settings.get('scene_threshold')
        log_input_expected_result("scene_threshold filtered", None, scene_threshold)
        self.assertIsNone(scene_threshold, "Non-project settings should be filtered out by UpdateProjectSettings")

    def test_update_project_settings_legacy(self):
        """Test UpdateProjectSettings with legacy settings compatibility"""

        project = SubtitleProject()

        # Test legacy settings that should be converted
        legacy_settings = SettingsType({
            'synopsis': 'Legacy description',  # Should become 'description'
            'characters': ['Old Character'],   # Should become part of 'names'
            'names': ['New Character'],        # Existing names to merge with
            'gpt_prompt': 'Legacy prompt',     # Should become 'prompt'
            'gpt_model': 'legacy-model',       # Should become 'model'
            'match_partial_words': True        # Should affect 'substitution_mode'
        })

        project.UpdateProjectSettings(legacy_settings)

        # Test that legacy conversions worked
        # synopsis -> description
        description = project.subtitles.settings.get('description')
        log_input_expected_result(description, 'Legacy description', description)
        self.assertEqual(description, 'Legacy description')

        # gpt_prompt -> prompt
        prompt = project.subtitles.settings.get('prompt')
        log_input_expected_result(prompt, 'Legacy prompt', prompt)
        self.assertEqual(prompt, 'Legacy prompt')

        # gpt_model -> model
        model = project.subtitles.settings.get('model')
        log_input_expected_result(model, 'legacy-model', model)
        self.assertEqual(model, 'legacy-model')

        # characters merged with names
        names = project.subtitles.settings.get_str_list('names')
        log_input_expected_result(names, ['New Character', 'Old Character'], names)
        self.assertIn('New Character', names)
        self.assertIn('Old Character', names)

        # match_partial_words -> substitution_mode
        substitution_mode = project.subtitles.settings.get('substitution_mode')
        log_input_expected_result(substitution_mode, 'Partial Words', substitution_mode)
        self.assertEqual(substitution_mode, 'Partial Words')

        # Verify original legacy keys were removed
        characters = project.subtitles.settings.get('characters')
        log_input_expected_result(characters, None, characters)
        self.assertIsNone(characters)

    def test_update_output_path(self):
        """Test UpdateOutputPath functionality thoroughly"""

        project = SubtitleProject()
        project.subtitles.sourcepath = self.test_srt_file
        project.subtitles.settings['target_language'] = 'Spanish'

        # Test basic output path generation
        project.UpdateOutputPath()

        output_path = project.subtitles.outputpath
        log_input_expected_result("output path generated", True, output_path is not None)
        self.assertIsNotNone(output_path)

        # Should contain target language in filename (case insensitive)
        if output_path:
            log_input_expected_result(output_path, True, 'spanish' in output_path.lower())
            self.assertIn('spanish', output_path.lower())

            # Should have .srt extension by default
            log_input_expected_result(output_path, True, output_path.endswith('.srt'))
            self.assertTrue(output_path.endswith('.srt'))

        # Test with custom path - UpdateOutputPath processes through GetOutputPath
        custom_path = os.path.join(self.temp_dir, "custom_output.vtt")
        # Need to also specify the extension since UpdateOutputPath uses the current file_format if available
        project.UpdateOutputPath(custom_path, '.vtt')

        new_output_path = project.subtitles.outputpath
        # GetOutputPath will add language suffix, so expect that behavior
        expected_custom_path = os.path.join(self.temp_dir, "custom_output.spanish.vtt")
        log_input_expected_result("custom output path with language", expected_custom_path, new_output_path)
        self.assertEqual(new_output_path, expected_custom_path)

        # Should update file format
        file_format = project.subtitles.file_format
        log_input_expected_result("file format updated", '.vtt', file_format)
        self.assertEqual(file_format, '.vtt')

        # Test with custom extension
        project.UpdateOutputPath(extension='.ass')

        ass_output_path = project.subtitles.outputpath
        if ass_output_path:
            log_input_expected_result(ass_output_path, True, ass_output_path.endswith('.ass'))
            self.assertTrue(ass_output_path.endswith('.ass'))

    def test_initialise_project_with_explicit_output_path(self):
        """Test InitialiseProject respects explicit output path (CLI scenario)"""

        project = SubtitleProject()

        # This tests the CLI scenario where an explicit output path is provided
        explicit_output = os.path.join(self.temp_dir, "explicit_output.vtt")
        project.InitialiseProject(self.test_srt_file, outputpath=explicit_output)

        # Verify the explicit output path was set
        actual_output = project.subtitles.outputpath
        log_input_expected_result("explicit output path respected", explicit_output, actual_output)
        self.assertEqual(actual_output, explicit_output, "InitialiseProject should respect explicit outputpath")

        # Verify file format was updated
        file_format = project.subtitles.file_format
        log_input_expected_result("file format from explicit path", '.vtt', file_format)
        self.assertEqual(file_format, '.vtt', "File format should be derived from explicit output path")

    def test_initialise_project_new_srt(self):
        """Test InitialiseProject with a new SRT file"""

        project = SubtitleProject()

        # Initialize with SRT file
        project.InitialiseProject(self.test_srt_file)

        # Verify project was initialized correctly
        log_input_expected_result("subtitles loaded", True, project.subtitles is not None)
        self.assertIsNotNone(project.subtitles)

        log_input_expected_result("has subtitles", True, project.subtitles.has_subtitles)
        self.assertTrue(project.subtitles.has_subtitles)

        line_count = project.subtitles.linecount
        expected_line_count = 64  # From chinese_dinner_data
        log_input_expected_result("line count", expected_line_count, line_count)
        self.assertEqual(line_count, expected_line_count)

        # Verify source path is set
        source_path = project.subtitles.sourcepath
        log_input_expected_result("source path", self.test_srt_file, source_path)
        self.assertEqual(source_path, self.test_srt_file)

        # Verify output path is generated
        output_path = project.subtitles.outputpath
        log_input_expected_result("output path generated", True, output_path is not None)
        self.assertIsNotNone(output_path)

        # Verify project file path is set
        expected_project_file = self.test_srt_file.replace('.srt', '.subtrans')
        actual_project_file = project.projectfile
        log_input_expected_result("project file path", expected_project_file, actual_project_file)
        self.assertEqual(actual_project_file, expected_project_file)

    def test_save_and_reload_project_preserves_settings(self):
        """Test saving and reloading project preserves custom settings"""

        # Create project with custom settings
        project = SubtitleProject(persistent=True)
        project.InitialiseProject(self.test_srt_file)

        # Add custom settings (only valid project settings)
        custom_settings = SettingsType({
            'target_language': 'French',
            'movie_name': 'Custom Movie',
            'description': 'Custom description',
            'names': ['Custom Character 1', 'Custom Character 2'],
            'provider': 'Custom Provider'
        })

        project.UpdateProjectSettings(custom_settings)

        # Batch the subtitles so we have scenes to save
        batcher = SubtitleBatcher(self.options)
        with project.GetEditor() as editor:
            editor.AutoBatch(batcher)

        # Save the project
        project.SaveProjectFile(self.test_project_file)

        # Create new project and load from file
        new_project = SubtitleProject()
        new_project.ReadProjectFile(self.test_project_file)

        # Verify custom settings were preserved
        test_cases = [
            ('target_language', 'French'),
            ('movie_name', 'Custom Movie'),
            ('description', 'Custom description'),
            ('provider', 'Custom Provider')
        ]

        for key, expected in test_cases:
            actual = new_project.subtitles.settings.get(key)
            log_input_expected_result(f"preserved setting '{key}'", expected, actual)
            self.assertEqual(actual, expected)

        # Verify names were preserved
        names = new_project.subtitles.settings.get_str_list('names')
        expected_names = ['Custom Character 1', 'Custom Character 2']
        log_input_expected_result(names, expected_names, names)
        self.assertEqual(names, expected_names)

        # Verify subtitles data was preserved
        original_line_count = project.subtitles.linecount
        new_line_count = new_project.subtitles.linecount
        log_input_expected_result("preserved line count", original_line_count, new_line_count)
        self.assertEqual(new_line_count, original_line_count)

        original_scene_count = project.subtitles.scenecount
        new_scene_count = new_project.subtitles.scenecount
        log_input_expected_result("preserved scene count", original_scene_count, new_scene_count)
        self.assertEqual(new_scene_count, original_scene_count)


    def test_initialise_project_existing_subtrans(self):
        """Test InitialiseProject with existing subtrans file"""

        # First create a project file
        project = SubtitleProject(persistent=True)
        project.InitialiseProject(self.test_srt_file)

        # Add some settings and batch
        settings = SettingsType({
            'target_language': 'German',
            'movie_name': 'Existing Project Movie'
        })
        project.UpdateProjectSettings(settings)

        batcher = SubtitleBatcher(self.options)
        with project.GetEditor() as editor:
            editor.AutoBatch(batcher)

        project.SaveProjectFile(self.test_project_file)

        # Now test initializing from the existing project file
        new_project = SubtitleProject()
        new_project.InitialiseProject(self.test_project_file)

        # Should load existing project
        log_input_expected_result("existing_project flag", True, new_project.existing_project)
        self.assertTrue(new_project.existing_project)

        log_input_expected_result("use_project_file flag", True, new_project.use_project_file)
        self.assertTrue(new_project.use_project_file)

        # Should preserve settings
        target_language = new_project.subtitles.settings.get('target_language')
        movie_name = new_project.subtitles.settings.get('movie_name')
        log_input_expected_result("preserved target_language", 'German', target_language)
        log_input_expected_result("preserved movie_name", 'Existing Project Movie', movie_name)
        self.assertEqual(target_language, 'German')
        self.assertEqual(movie_name, 'Existing Project Movie')

        # Should have scenes from batching
        scene_count = new_project.subtitles.scenecount
        log_input_expected_result("scene count > 0", True, scene_count > 0)
        self.assertGreater(scene_count, 0)

    def test_initialise_project_existing_subtrans_reload(self):
        """Test InitialiseProject with existing subtrans file and reload_subtitles=True"""

        # Create a project file first
        project = SubtitleProject(persistent=True)
        project.InitialiseProject(self.test_srt_file)

        settings = SettingsType({
            'target_language': 'Portuguese',
            'movie_name': 'Reload Test Movie'
        })
        project.UpdateProjectSettings(settings)

        batcher = SubtitleBatcher(self.options)
        with project.GetEditor() as editor:
            editor.AutoBatch(batcher)

        project.SaveProjectFile(self.test_project_file)

        # Modify the source SRT file to simulate changes
        modified_srt_content = """1
00:00:01,000 --> 00:00:03,000
Modified subtitle line 1

2
00:00:04,000 --> 00:00:06,000
Modified subtitle line 2
"""
        with open(self.test_srt_file, 'w', encoding='utf-8') as f:
            f.write(modified_srt_content)

        # Initialize with reload_subtitles=True
        new_project = SubtitleProject()
        new_project.InitialiseProject(self.test_project_file, reload_subtitles=True)

        # Should preserve project settings
        target_language = new_project.subtitles.settings.get('target_language')
        movie_name = new_project.subtitles.settings.get('movie_name')
        log_input_expected_result("preserved target_language", 'Portuguese', target_language)
        log_input_expected_result("preserved movie_name", 'Reload Test Movie', movie_name)
        self.assertEqual(target_language, 'Portuguese')
        self.assertEqual(movie_name, 'Reload Test Movie')

        # Should have reloaded subtitle content
        line_count = new_project.subtitles.linecount
        expected_line_count = 2  # Modified content has 2 lines
        log_input_expected_result("reloaded line count", expected_line_count, line_count)
        self.assertEqual(line_count, expected_line_count)

        # Should have subtitle text from reloaded file
        if new_project.subtitles.originals:
            first_line_text = new_project.subtitles.originals[0].text
            log_input_expected_result("reloaded first line", "Modified subtitle line 1", first_line_text)
            self.assertEqual(first_line_text, "Modified subtitle line 1")

    def test_get_project_settings(self):
        """Test GetProjectSettings method returns expected settings"""

        project = SubtitleProject()

        # Add mix of valid project settings and non-project settings using UpdateProjectSettings
        # This should only store valid project settings
        project.UpdateProjectSettings(SettingsType({
            'target_language': 'Japanese',       # Valid and non-empty
            'movie_name': 'Test Movie',          # Valid and non-empty
            'provider': 'Test Provider',         # Valid and non-empty
            'description': 'Valid Description',  # Valid and non-empty
            'names': ['Character'],              # Valid list
            'substitutions': None,               # Valid key but None value - should be excluded
            'prompt': '',                        # Valid key but empty string - should be excluded
            'invalid_setting': 'some_value',     # Invalid key - should be filtered by UpdateProjectSettings
            'format': '.srt'                     # Valid and non-empty
        }))

        project_settings = project.GetProjectSettings()

        expected_included = [
            ('target_language', 'Japanese'),
            ('movie_name', 'Test Movie'),
            ('provider', 'Test Provider'),
            ('description', 'Valid Description'),
            ('names', ['Character']),
            ('format', '.srt')
        ]

        for key, expected_value in expected_included:
            actual_value = project_settings.get(key)
            log_input_expected_result(f"includes '{key}'", expected_value, actual_value)
            self.assertEqual(actual_value, expected_value, f"GetProjectSettings should include valid non-empty setting '{key}'")

        # Test what SHOULD be excluded (None and empty strings)
        excluded_none_empty = ['substitutions', 'prompt']
        for key in excluded_none_empty:
            log_input_expected_result(f"excludes '{key}' (None/empty)", False, key in project_settings)
            self.assertNotIn(key, project_settings, f"GetProjectSettings should exclude None/empty setting '{key}'")

        # CRITICAL: Test that invalid settings were filtered out by UpdateProjectSettings
        # GetProjectSettings should only see valid project settings that passed through UpdateProjectSettings
        invalid_in_result = project_settings.get('invalid_setting')
        log_input_expected_result(invalid_in_result, None, invalid_in_result)
        self.assertIsNone(invalid_in_result, "Invalid settings should have been filtered out by UpdateProjectSettings")

    def test_get_project_filepath(self):
        """Test GetProjectFilepath method"""

        project = SubtitleProject()

        # Test with SRT file (use os.path.normpath for Windows compatibility)
        srt_path = "/path/to/movie.srt"
        project_path = project.GetProjectFilepath(srt_path)
        expected_path = os.path.normpath("/path/to/movie.subtrans")
        actual_path = os.path.normpath(project_path)
        log_input_expected_result("SRT to subtrans", expected_path, actual_path)
        self.assertEqual(actual_path, expected_path)

        # Test with already subtrans file
        subtrans_path = "/path/to/movie.subtrans"
        project_path = project.GetProjectFilepath(subtrans_path)
        expected_path = os.path.normpath(subtrans_path)
        actual_path = os.path.normpath(project_path)
        log_input_expected_result("subtrans unchanged", expected_path, actual_path)
        self.assertEqual(actual_path, expected_path)

        # Test with no extension
        no_ext_path = "/path/to/movie"
        project_path = project.GetProjectFilepath(no_ext_path)
        expected_path = os.path.normpath("/path/to/movie.subtrans")
        actual_path = os.path.normpath(project_path)
        log_input_expected_result("no extension to subtrans", expected_path, actual_path)
        self.assertEqual(actual_path, expected_path)

    def test_get_backup_filepath(self):
        """Test GetBackupFilepath method"""

        project = SubtitleProject()

        filepath = "/path/to/movie.srt"
        backup_path = project.GetBackupFilepath(filepath)
        expected_backup = os.path.normpath("/path/to/movie.subtrans-backup")
        actual_backup = os.path.normpath(backup_path)
        log_input_expected_result("backup filepath", expected_backup, actual_backup)
        self.assertEqual(actual_backup, expected_backup)

    def test_properties(self):
        """Test project properties"""

        project = SubtitleProject()

        # Test initial property values
        log_input_expected_result("initial target_language", None, project.target_language)
        log_input_expected_result("initial task_type", None, project.task_type)
        log_input_expected_result("initial movie_name", None, project.movie_name)
        log_input_expected_result("initial any_translated", False, project.any_translated)
        log_input_expected_result("initial all_translated", False, project.all_translated)

        self.assertIsNone(project.target_language)
        self.assertIsNone(project.task_type)
        self.assertIsNone(project.movie_name)
        self.assertFalse(project.any_translated)
        self.assertFalse(project.all_translated)

        # Update settings and test properties reflect changes
        settings = SettingsType({
            'target_language': 'Russian',
            'task_type': 'translation',
            'movie_name': 'Property Test Movie'
        })
        project.UpdateProjectSettings(settings)

        log_input_expected_result("updated target_language", 'Russian', project.target_language)
        log_input_expected_result("updated task_type", 'translation', project.task_type)
        log_input_expected_result("updated movie_name", 'Property Test Movie', project.movie_name)

        self.assertEqual(project.target_language, 'Russian')
        self.assertEqual(project.task_type, 'translation')
        self.assertEqual(project.movie_name, 'Property Test Movie')

    def test_get_editor_marks_project_dirty(self):
        """GetEditor should mark the project as needing to be written after edits"""

        project = SubtitleProject(persistent=True)

        log_input_expected_result("initial needs_writing", False, project.needs_writing)
        self.assertFalse(project.needs_writing)

        with project.GetEditor() as editor:
            new_scene = SubtitleScene({'number': 1})
            editor.AddScene(new_scene)

        log_input_expected_result("needs_writing after edit", True, project.needs_writing)
        self.assertTrue(project.needs_writing)

    @skip_if_debugger_attached
    def test_get_editor_exception_does_not_mark_project_dirty(self):
        """GetEditor should not mark the project dirty if the edit fails"""
        project = SubtitleProject(persistent=True)

        with self.assertRaises(ValueError):
            with project.GetEditor():
                raise ValueError("Test edit failure")

        log_input_expected_result("needs_writing after failed edit", False, project.needs_writing)
        self.assertFalse(project.needs_writing)


if __name__ == '__main__':
    unittest.main()
