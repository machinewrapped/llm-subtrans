import json
import os
import logging
import threading

from PySubtrans.Helpers import GetOutputPath
from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Parse import ParseNames
from PySubtrans.Options import Options, SettingsType
from PySubtrans.Substitutions import Substitutions
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleEditor import SubtitleEditor
from PySubtrans.SubtitleError import SubtitleError, TranslationAbortedError
from PySubtrans.SubtitleFormatRegistry import SubtitleFormatRegistry
from PySubtrans.Subtitles import Subtitles

from PySubtrans.SubtitleScene import SubtitleScene
from PySubtrans.SubtitleSerialisation import SubtitleDecoder, SubtitleEncoder
from PySubtrans.SubtitleTranslator import SubtitleTranslator
from PySubtrans.TranslationEvents import TranslationEvents

default_encoding = os.getenv('DEFAULT_ENCODING', 'utf-8')

class SubtitleProject:
    """
    Handles loading, saving and creation of project files for LLM-Subtrans
    """
    DEFAULT_PROJECT_SETTINGS : SettingsType = SettingsType({
        'provider': None,
        'model': None,
        'target_language': None,
        'prompt': None,
        'task_type': None,
        'instructions': None,
        'retry_instructions': None,
        'movie_name': None,
        'description': None,
        'names': None,
        'substitutions': None,
        'substitution_mode': None,
        'include_original': None,
        'add_right_to_left_markers': None,
        'instruction_file': None,
        'format': None
    })
    def __init__(self, persistent : bool = False):
        """
        A subtitle translation project. 
        
        Can be initialised from a project file or a subtitle file,
        or manually configured by assigning a SubtitleFile and updating settings if necessary.
        
        :param persistent: if True, the project will be saved to disk and automatically reloaded next time
        """
        self.subtitles : Subtitles = Subtitles(settings=self.DEFAULT_PROJECT_SETTINGS)
        self.events = TranslationEvents()
        self.projectfile : str|None = None
        self.existing_project : bool = False
        self.needs_writing : bool = False
        self.lock = threading.RLock()

        # By default the project is not persistent, i.e. it will not be saved to a file and automatically reloaded next time
        self.use_project_file : bool = persistent

        # By default the translated subtitles will be written to file
        self.write_translation = True

    @property
    def target_language(self) -> str|None:
        return self.subtitles.target_language if self.subtitles else None
    
    @property
    def task_type(self) -> str|None:
        return self.subtitles.task_type if self.subtitles else None

    @property
    def movie_name(self) -> str|None:
        return self.subtitles.movie_name if self.subtitles else None

    @property
    def any_translated(self) -> bool:
        with self.lock:
            return bool(self.subtitles and self.subtitles.any_translated)

    @property
    def all_translated(self) -> bool:
        with self.lock:
            return bool(self.subtitles and self.subtitles.all_translated)

    def InitialiseProject(self, filepath : str, outputpath : str|None = None, reload_subtitles : bool = False):
        """
        Initialize the project by either loading an existing project file or creating a new one.
        Load the subtitles to be translated, either from the project file or the source file.

        :param filepath: the path to the project or a source subtitle file
        :param outputpath: the path to write the translated subtitles to
        :param reload_subtitles: force reloading subtitles from source file
        """
        filepath = os.path.normpath(filepath)
        sourcepath : str = filepath
        self.projectfile = self.GetProjectFilepath(filepath or "subtitles")

        project_file_exists : bool = os.path.exists(self.projectfile)
        project_settings : SettingsType = SettingsType()

        # If initialised with a project file, we are implicitly using a project file
        if filepath == self.projectfile:
            self.use_project_file = True

        read_project : bool = self.use_project_file and project_file_exists
        load_subtitles : bool = reload_subtitles or not read_project

        if not read_project and not load_subtitles:
            raise SubtitleError(_("No project or subtitles to load"))

        if project_file_exists and not read_project:
            logging.warning(_("Project file {} exists but will not be used").format(self.projectfile))

        if read_project:
            logging.info(_("Loading existing project file {}").format(self.projectfile))

            self.ReadProjectFile(self.projectfile)
            project_settings = self.GetProjectSettings()

            subtitles : Subtitles = self.subtitles
            if subtitles:
                self.UpdateOutputPath()

                outputpath = outputpath or GetOutputPath(self.projectfile, subtitles.target_language, subtitles.file_format)
                sourcepath = subtitles.sourcepath if subtitles.sourcepath else sourcepath               
                logging.info(_("Project file loaded"))

                if subtitles.scenes:
                    self.existing_project = True
                    self.needs_writing = False
                    load_subtitles = reload_subtitles
                    if load_subtitles:
                        logging.info(_("Reloading subtitles from the source file"))

                else:
                    logging.error(_("Unable to read project file, starting afresh"))
                    load_subtitles = True

        if load_subtitles:
            try:
                # (re)load the source subtitle file if required
                self.LoadSubtitleFile(sourcepath)

            except Exception as e:
                logging.error(_("Failed to load subtitle file {}: {}").format(filepath, str(e)))
                raise

        subtitles = self.subtitles

        if not subtitles or not subtitles.has_subtitles:
            raise ValueError(_("No subtitles to translate in {}").format(filepath))

        if outputpath:
            subtitles.outputpath = outputpath
            subtitles.file_format = SubtitleFormatRegistry.get_format_from_filename(outputpath)
            self.needs_writing = self.use_project_file

        # Re-apply any project settings and update for compatibility
        if read_project:
            self.UpdateProjectSettings(project_settings)

    def UpdateProjectSettings(self, settings: SettingsType) -> None:
        """
        Update the project settings with validation and filtering
        """
        if isinstance(settings, Options):
            settings = SettingsType(settings)

        with self.lock:
            if not self.subtitles:
                return

            # Filter settings to only include known project settings (original logic)
            filtered_settings = SettingsType({key: settings[key] for key in settings if key in self.DEFAULT_PROJECT_SETTINGS})

            # Process names and substitutions
            if 'names' in filtered_settings:
                names_list = filtered_settings.get('names', [])
                filtered_settings['names'] = ParseNames(names_list)

            if 'substitutions' in filtered_settings:
                substitutions_list = filtered_settings.get('substitutions', [])
                if substitutions_list:
                    filtered_settings['substitutions'] = Substitutions.Parse(substitutions_list)

            # Apply compatibility updates
            self._update_compatibility(filtered_settings)

            # Check if there are actual changes before updating
            common_keys = filtered_settings.keys() & self.subtitles.settings.keys()
            new_keys = filtered_settings.keys() - self.subtitles.settings.keys()

            if not all(filtered_settings.get(key) == self.subtitles.settings.get(key) for key in common_keys) or new_keys:
                self.subtitles.UpdateSettings(filtered_settings)
                self.needs_writing = bool(self.subtitles.scenes) and self.use_project_file

    def UpdateOutputPath(self, path: str|None = None, extension: str|None = None) -> None:
        """
        Set or generate the output path for the translated subtitles
        """
        path = path or self.subtitles.sourcepath
        extension = extension or self.subtitles.file_format
        if not extension:
            extension = SubtitleFormatRegistry.get_format_from_filename(path) if path else None
            extension = extension or '.srt'

        if extension == ".subtrans":
            raise SubtitleError("Cannot use .subtrans as output format")

        outputpath = GetOutputPath(path, self.target_language, extension)
        self.subtitles.outputpath = outputpath
        self.subtitles.file_format = extension

    def SaveOriginal(self, outputpath : str|None = None):
        """
        Write the original subtitles to a file
        """
        try:
            with self.lock:
                outputpath = outputpath or GetOutputPath(self.subtitles.sourcepath, None, self.subtitles.file_format)
                self.subtitles.SaveOriginal(outputpath)

        except Exception as e:
            logging.error(_("Unable to save original subtitles: {}").format(e))

    def SaveTranslation(self, outputpath : str|None = None):
        """
        Write output file
        """
        try:
            with self.lock:
                self.subtitles.SaveTranslation(outputpath)

        except Exception as e:
            logging.error(_("Unable to save translation: {}").format(e))

    def GetProjectFilepath(self, filepath : str) -> str:
        """
        Calculate the project file path based on the source file path
        """
        path, ext = os.path.splitext(filepath)
        filepath = filepath if ext == '.subtrans' else f"{path}.subtrans"
        return os.path.normpath(filepath)

    def GetBackupFilepath(self, filepath : str) -> str:
        """
        Get the backup file path for the project file
        """
        projectfile = self.GetProjectFilepath(filepath)
        return f"{projectfile}-backup"

    def LoadSubtitleFile(self, filepath: str) -> Subtitles:
        """
        Load subtitles from a file, auto-detecting the format by extension
        """
        with self.lock:
            # Pass default settings for new subtitle files
            self.subtitles = Subtitles(filepath, settings=self.DEFAULT_PROJECT_SETTINGS)
            self.subtitles.LoadSubtitles()

        return self.subtitles

    def SaveProject(self):
        """
        Save the project file or translation file as needed
        """
        with self.lock:
            if self.needs_writing:
                if self.use_project_file:
                    self.UpdateProjectFile()
                if self.any_translated and self.write_translation:
                    self.SaveTranslation()
                self.needs_writing = False

    def SaveProjectFile(self, projectfile : str|None = None) -> None:
        """
        Write a set of subtitles to a project file
        """
        with self.lock:
            if not self.subtitles:
                raise Exception("Can't write project file, no subtitles")

            if not isinstance(self.subtitles, Subtitles):
                raise Exception("Can't write project file, wrong content type")

            if not self.subtitles.scenes:
                raise Exception("Can't write project file, no scenes")

            if not projectfile:
                projectfile = self.projectfile
            elif projectfile and not self.projectfile:
                self.projectfile = self.GetProjectFilepath(projectfile)

            if not projectfile:
                raise Exception("No file path provided")

            self.WriteProjectToFile(projectfile, encoder_class=SubtitleEncoder)

            self.needs_writing = False

    def SaveBackupFile(self) -> None:
        """
        Save a backup copy of the project
        """
        with self.lock:
            if self.subtitles and self.projectfile:
                backupfile = self.GetBackupFilepath(self.projectfile)
                self.WriteProjectToFile(backupfile, encoder_class=SubtitleEncoder)

    def ReadProjectFile(self, filepath : str|None = None) -> Subtitles|None:
        """
        Load scenes, subtitles and context from a project file
        """
        try:
            filepath = filepath or self.projectfile
            if not filepath:
                raise ValueError(_("No project file path provided"))

            with self.lock:
                logging.info(_("Reading project data from {}").format(str(filepath)))

                with open(filepath, 'r', encoding=default_encoding, newline='') as f:
                    self.subtitles: Subtitles = json.load(f, cls=SubtitleDecoder)

                with SubtitleEditor(self.subtitles) as editor:
                    editor.Sanitise()

                return self.subtitles

        except FileNotFoundError:
            logging.error(_("Project file {} not found").format(filepath))
            return None

        except json.JSONDecodeError as e:
            logging.error(_("Error decoding JSON file: {}").format(e))
            return None

    def UpdateProjectFile(self) -> None:
        """
        Save the project file if it needs updating
        """
        with self.lock:
            if self.needs_writing and self.subtitles and self.subtitles.scenes:
                self.SaveProjectFile()

    def GetProjectSettings(self) -> SettingsType:
        """
        Return a dictionary of non-empty settings from the project file
        """
        if not self.subtitles:
            return SettingsType()

        return SettingsType({ key : value for key, value in self.subtitles.settings.items() if value is not None and (value != '' or isinstance(value, list)) })

    def WriteProjectToFile(self, projectfile: str, encoder_class: type|None = None) -> None:
        """
        Save the project settings to a JSON file
        """
        if encoder_class is None:
            raise ValueError("No encoder provided")

        projectfile = os.path.normpath(projectfile)
        logging.info(_("Writing project data to {}").format(str(projectfile)))

        with self.lock:
            with open(projectfile, 'w', encoding=default_encoding) as f:
                project_json = json.dumps(self.subtitles, cls=encoder_class, ensure_ascii=False, indent=4) # type: ignore
                f.write(project_json)

    def TranslateSubtitles(self, translator : SubtitleTranslator) -> None:
        """
        One-stop shop: Use the translation provider to translate a project, then save the translation.
        """
        if not self.subtitles:
            raise Exception("No subtitles to translate")

        # Prime new project files
        self.UpdateProjectFile()

        save_translation : bool = self.write_translation and not translator.preview

        try:
            translator.events.preprocessed += self._on_preprocessed # type: ignore
            translator.events.batch_translated += self._on_batch_translated # type: ignore
            translator.events.scene_translated += self._on_scene_translated # type: ignore

            translator.TranslateSubtitles(self.subtitles)

            translator.events.preprocessed -= self._on_preprocessed # type: ignore
            translator.events.batch_translated -= self._on_batch_translated # type: ignore
            translator.events.scene_translated -= self._on_scene_translated # type: ignore

            if save_translation and not translator.aborted:
                self.SaveTranslation()

        except TranslationAbortedError:
            logging.info(_("Translation aborted"))

        except Exception as e:
            if save_translation and self.subtitles.any_translated:
                logging.warning(_("Translation failed, saving partial results"))
                self.SaveTranslation()

            logging.error(_("Failed to translate subtitles: {}").format(str(e)))
            raise

    def TranslateScene(self, translator : SubtitleTranslator, scene_number : int, batch_numbers : list[int]|None = None, line_numbers : list[int]|None = None) -> SubtitleScene|None:
        """
        Pass batches of subtitles to the translation engine.
        """
        if not self.subtitles:
            raise Exception("No subtitles to translate")

        translator.events.preprocessed += self._on_preprocessed             # type: ignore
        translator.events.batch_translated += self._on_batch_translated     # type: ignore

        try:
            scene : SubtitleScene = self.subtitles.GetScene(scene_number)

            scene.errors = []

            translator.TranslateScene(self.subtitles, scene, batch_numbers=batch_numbers, line_numbers=line_numbers)

            return scene

        except TranslationAbortedError:
            pass

        finally:
            translator.events.preprocessed -= self._on_preprocessed # type: ignore
            translator.events.batch_translated -= self._on_batch_translated # type: ignore

    def _on_preprocessed(self, scenes) -> None:
        logging.debug("Pre-processing finished")
        self.events.preprocessed(scenes)

    def _on_batch_translated(self, batch) -> None:
        logging.debug("Batch translated")
        self.needs_writing = self.use_project_file
        self.events.batch_translated(batch)

    def _on_scene_translated(self, scene) -> None:
        logging.debug("Scene translated")
        self.needs_writing = self.use_project_file
        self.events.scene_translated(scene)

    def _update_compatibility(self, settings: SettingsType) -> None:
        """
        Update settings for compatibility with older versions
        """
        if not settings.get('description') and settings.get('synopsis'):
            settings['description'] = settings.get('synopsis')

        if settings.get('characters'):
            names = settings.get_str_list('names')
            names.extend(settings.get_str_list('characters'))
            settings['names'] = names
            del settings['characters']

        if settings.get('gpt_prompt'):
            settings['prompt'] = settings['gpt_prompt']
            del settings['gpt_prompt']

        if settings.get('gpt_model'):
            settings['model'] = settings['gpt_model']
            del settings['gpt_model']

        if not settings.get('substitution_mode'):
            settings['substitution_mode'] = "Partial Words" if settings.get('match_partial_words') else "Auto"


