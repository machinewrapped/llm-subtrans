from GuiSubtrans.ProjectDataModel import ProjectDataModel
from .DataModelHelpers import CreateTestDataModel
from PySubtrans.Helpers.TestCases import SubtitleTestCase
from PySubtrans.Helpers.Tests import log_input_expected_result, log_test_name
from PySubtrans.Options import Options, SettingsType
from PySubtrans.Subtitles import Subtitles
from PySubtrans.Formats.SrtFileHandler import SrtFileHandler
from PySubtrans.SubtitleProject import SubtitleProject
from ..TestData.chinese_dinner import chinese_dinner_data

class DataModelTests(SubtitleTestCase):
    def test_ProjectOptionsDecoupling(self):
        """Test that project options and global options remain properly decoupled"""
        
        # Create global options with a specific provider and model
        global_options = Options({
            'provider': 'Dummy GPT',
            'provider_settings': {
                'Dummy GPT': SettingsType({'model': 'gpt-4'})
            },
            'target_language': 'Spanish'
        })
        
        # Create a project using the proper initialization pattern
        project = SubtitleProject()
        
        # Simulate loading a subtitle file with project settings
        subtitles = Subtitles()
        original_subtitles = chinese_dinner_data.get_str('original')
        if original_subtitles is None:
            self.fail("Couldn't load subtitles")
            return

        subtitles.LoadSubtitlesFromString(original_subtitles, SrtFileHandler())
        
        # Set the project's subtitle file and apply test-specific project settings
        project.subtitles = subtitles
        # Apply the project-specific settings that were set on the SubtitleFile
        project.UpdateProjectSettings(SettingsType({
            'provider': 'Dummy Claude',
            'model': 'claude-1000-sonnet',
            'target_language': 'French',
            'movie_name': 'Chinese Dinner'
        }))
        datamodel = ProjectDataModel(project, global_options)
        
        # Verify initial state - project options should override global options for project-specific settings
        log_input_expected_result("Initial provider", 'Dummy Claude', datamodel.project_options.provider)
        log_input_expected_result("Initial target_language", 'French', datamodel.project_options.target_language)
        movie_name = datamodel.project_options.get_str('movie_name')
        log_input_expected_result("Initial movie_name", 'Chinese Dinner', movie_name)
        
        self.assertEqual(datamodel.project_options.provider, 'Dummy Claude')
        self.assertEqual(datamodel.project_options.target_language, 'French')
        self.assertIsNotNone(movie_name)
        self.assertEqual(movie_name, 'Chinese Dinner')
        
        # Update global options - should affect non-project-specific settings
        new_global_settings = SettingsType({
            'provider': 'Gemini',
            'provider_settings': {
                'Gemini': SettingsType({'model': 'gemini-pro'})
            },
            'max_threads': 8,
            'retry_on_error': False
        })
        
        datamodel.UpdateSettings(new_global_settings)
        
        # Project-specific settings should be preserved
        movie_name_after = datamodel.project_options.get_str('movie_name')
        max_threads = datamodel.project_options.get_int('max_threads')
        retry_on_error = datamodel.project_options.get_bool('retry_on_error')
        
        log_input_expected_result("Provider after global update", 'Dummy Claude', datamodel.project_options.provider)
        log_input_expected_result("Target language after global update", 'French', datamodel.project_options.target_language)
        log_input_expected_result("Movie name after global update", 'Chinese Dinner', movie_name_after)
        
        self.assertEqual(datamodel.project_options.provider, 'Dummy Claude')
        self.assertEqual(datamodel.project_options.target_language, 'French')
        self.assertIsNotNone(movie_name_after)
        self.assertEqual(movie_name_after, 'Chinese Dinner')
        
        # Non-project-specific settings should be updated
        log_input_expected_result("Max threads after global update", 8, max_threads)
        log_input_expected_result("Retry on error after global update", False, retry_on_error)
        
        self.assertIsNotNone(max_threads)
        self.assertEqual(max_threads, 8)
        self.assertIsNotNone(retry_on_error)
        self.assertEqual(retry_on_error, False)
        
    def test_UpdateProjectSettings(self):
        """Test that updating project settings works correctly"""
        
        datamodel = CreateTestDataModel(chinese_dinner_data, self.options)
        if not datamodel.project:
            self.fail("Failed to create test project")
            return
            
        original_provider = datamodel.project_options.provider
        
        # Update project-specific settings
        project_updates = SettingsType({
            'target_language': 'Japanese',
            'movie_name': 'Updated Movie Name',
            'description': 'Updated description'
        })
        
        datamodel.UpdateProjectSettings(project_updates)
        
        # Verify project settings were updated
        updated_movie_name = datamodel.project_options.get_str('movie_name')
        updated_description = datamodel.project_options.get_str('description')
        
        log_input_expected_result("Updated target language", 'Japanese', datamodel.project_options.target_language)
        log_input_expected_result("Updated movie name", 'Updated Movie Name', updated_movie_name)
        log_input_expected_result("Updated description", 'Updated description', updated_description)
        
        self.assertEqual(datamodel.project_options.target_language, 'Japanese')
        self.assertIsNotNone(updated_movie_name)
        self.assertEqual(updated_movie_name, 'Updated Movie Name')
        self.assertIsNotNone(updated_description)
        self.assertEqual(updated_description, 'Updated description')
        
        # Verify provider wasn't changed (should remain from original options)
        log_input_expected_result("Provider unchanged", original_provider, datamodel.project_options.provider)
        self.assertEqual(datamodel.project_options.provider, original_provider)
        
    def test_ProjectOptionsIsolation(self):
        """Test that multiple projects maintain separate option states"""
        
        # Use shared global options to test that global settings propagate correctly
        global_options = Options({
            'provider': 'Dummy GPT',
            'target_language': 'English'
        })
        
        # Create first project
        project1 = SubtitleProject()
        project1_file = Subtitles()
        original_subtitles1 = chinese_dinner_data.get_str('original')
        if original_subtitles1 is None:
            self.fail("Couldn't load subtitles")
            return
        project1_file.LoadSubtitlesFromString(original_subtitles1, SrtFileHandler())
        project1.subtitles = project1_file
        project1.UpdateProjectSettings(SettingsType({
            'target_language': 'Spanish',
            'movie_name': 'Project 1'
        }))
        datamodel1 = ProjectDataModel(project1, global_options)
        
        # Create second project
        project2 = SubtitleProject()
        project2_file = Subtitles()
        original_subtitles2 = chinese_dinner_data.get_str('original')
        if original_subtitles2 is None:
            self.fail("Couldn't load subtitles")
            return

        project2_file.LoadSubtitlesFromString(original_subtitles2, SrtFileHandler())
        project2.subtitles = project2_file
        project2.UpdateProjectSettings(SettingsType({
            'target_language': 'French',
            'movie_name': 'Project 2'
        }))
        datamodel2 = ProjectDataModel(project2, global_options)
        
        # Verify initial isolation
        project1_movie_name = datamodel1.project_options.get_str('movie_name')
        project2_movie_name = datamodel2.project_options.get_str('movie_name')
        
        log_input_expected_result("Project 1 target language", 'Spanish', datamodel1.project_options.target_language)
        log_input_expected_result("Project 2 target language", 'French', datamodel2.project_options.target_language)
        log_input_expected_result("Project 1 movie name", 'Project 1', project1_movie_name)
        log_input_expected_result("Project 2 movie name", 'Project 2', project2_movie_name)
        
        self.assertEqual(datamodel1.project_options.target_language, 'Spanish')
        self.assertEqual(datamodel2.project_options.target_language, 'French')
        self.assertIsNotNone(project1_movie_name)
        self.assertEqual(project1_movie_name, 'Project 1')
        self.assertIsNotNone(project2_movie_name)
        self.assertEqual(project2_movie_name, 'Project 2')
        
        # Update global settings on project 1
        datamodel1.UpdateSettings(SettingsType({
            'provider': 'Dummy Claude',
            'max_threads': 4
        }))
        
        # Project 1 should have updated non-project-specific settings but kept project-specific ones
        project1_max_threads = datamodel1.project_options.get_int('max_threads')
        project1_movie_name_after = datamodel1.project_options.get_str('movie_name')
        project2_movie_name_after = datamodel2.project_options.get_str('movie_name')
        project2_max_threads = datamodel2.project_options.get_int('max_threads')
        
        log_input_expected_result("Project 1 max threads after update", 4, project1_max_threads)
        log_input_expected_result("Project 1 target language after update", 'Spanish', datamodel1.project_options.target_language)
        log_input_expected_result("Project 1 movie name after update", 'Project 1', project1_movie_name_after)
        
        self.assertIsNotNone(project1_max_threads)
        self.assertEqual(project1_max_threads, 4)
        self.assertEqual(datamodel1.project_options.target_language, 'Spanish')
        self.assertIsNotNone(project1_movie_name_after)
        self.assertEqual(project1_movie_name_after, 'Project 1')
        
        # Project 2 should preserve project-specific settings but get global updates
        log_input_expected_result("Project 2 target language after project 1 update", 'French', datamodel2.project_options.target_language)
        log_input_expected_result("Project 2 movie name after project 1 update", 'Project 2', project2_movie_name_after)
        log_input_expected_result("Project 2 max threads after project 1 update", 4, project2_max_threads)
        
        self.assertEqual(datamodel2.project_options.target_language, 'French')
        self.assertIsNotNone(project2_movie_name_after)
        self.assertEqual(project2_movie_name_after, 'Project 2')
        # Global settings like max_threads should propagate to all projects sharing global options
        self.assertIsNotNone(project2_max_threads)
        self.assertEqual(project2_max_threads, 4)
        
    def test_ProviderSettingsIsolation(self):
        """Test that provider settings remain isolated between project and global options"""
        
        global_options = Options({
            'provider': 'Dummy GPT',
            'provider_settings': {
                'Dummy GPT': SettingsType({
                    'model': 'gpt-3.5-turbo',
                    'api_key': 'global_key'
                })
            }
        })
        
        # Create project with different provider settings
        project = SubtitleProject()
        subtitles = Subtitles()
        original_subtitles3 = chinese_dinner_data.get_str('original')
        if original_subtitles3 is None:
            self.fail("Couldn't load subtitles")
            return
        subtitles.LoadSubtitlesFromString(original_subtitles3, SrtFileHandler())
        project.subtitles = subtitles
        project.UpdateProjectSettings(SettingsType({
            'provider': 'Dummy GPT',
            'model': 'gpt-4'
        }))
        datamodel = ProjectDataModel(project, global_options)
        
        # Update provider settings through datamodel
        datamodel.UpdateProviderSettings(SettingsType({
            'model': 'gpt-4-turbo'
        }))
        
        # Check that project provider settings were updated
        current_settings = datamodel.provider_settings
        current_model = current_settings.get_str('model')
        log_input_expected_result("Provider model after update", 'gpt-4-turbo', current_model)
        self.assertIsNotNone(current_model)
        self.assertEqual(current_model, 'gpt-4-turbo')
        
        # Verify global options weren't affected
        global_provider_settings = global_options.provider_settings.get('Dummy GPT', SettingsType())
        global_model = global_provider_settings.get_str('model')
        log_input_expected_result("Global provider model unchanged", 'gpt-3.5-turbo', global_model)
        self.assertIsNotNone(global_model)
        self.assertEqual(global_model, 'gpt-3.5-turbo')
        
    def test_UpdateSettingsWithNoneProject(self):
        """Test UpdateSettings behavior when no project is loaded"""
        
        global_options = Options({
            'provider': 'Dummy GPT',
            'target_language': 'English'
        })
        
        # Create datamodel without project
        datamodel = ProjectDataModel(None, global_options)
        
        # Update settings
        new_settings = SettingsType({
            'provider': 'Dummy Claude',
            'target_language': 'Spanish',
            'max_threads': 6
        })
        
        datamodel.UpdateSettings(new_settings)
        
        # All settings should be updated since there's no project to restore from (this is a bit of a nonsense test)
        max_threads_no_project = datamodel.project_options.get_int('max_threads')
        
        log_input_expected_result("Provider with no project", 'Dummy Claude', datamodel.project_options.provider)
        log_input_expected_result("Target language with no project", 'Spanish', datamodel.project_options.target_language)
        log_input_expected_result("Max threads with no project", 6, max_threads_no_project)
        
        self.assertEqual(datamodel.project_options.provider, 'Dummy Claude')
        self.assertEqual(datamodel.project_options.target_language, 'Spanish')
        self.assertIsNotNone(max_threads_no_project)
        self.assertEqual(max_threads_no_project, 6)

