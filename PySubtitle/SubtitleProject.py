import json
import os
import logging
import threading

from PySubtitle.Helpers import GetOutputPath
from PySubtitle.Helpers.Localization import _
from PySubtitle.Options import Options, SettingsType
from PySubtitle.SettingsType import SettingsType
from PySubtitle.SubtitleError import SubtitleError, TranslationAbortedError
from PySubtitle.Subtitles import Subtitles

from PySubtitle.SubtitleBatch import SubtitleBatch
from PySubtitle.SubtitleScene import SubtitleScene
from PySubtitle.SubtitleSerialisation import SubtitleDecoder, SubtitleEncoder
from PySubtitle.SubtitleTranslator import SubtitleTranslator
from PySubtitle.TranslationEvents import TranslationEvents

default_encoding = os.getenv('DEFAULT_ENCODING', 'utf-8')

class SubtitleProject:
    """
    Handles loading, saving and creation of project files for LLM-Subtrans
    """
    def __init__(self, persistent : bool = False):
        """
        A subtitle translation project. 
        
        Can be initialised from a project file or a subtitle file,
        or manually configured by assigning a SubtitleFile and updating settings if necessary.
        
        :param persistent: if True, the project will be saved to disk and automatically reloaded next time
        """
        self.subtitles : Subtitles = Subtitles()
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

        :param filepath: the path to the project or a source subtitle file (in .srt format) to be translated
        :param outputpath: the path to write the translated subtitles too (a default path is used if None specified)
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

        if project_file_exists and not read_project:
            logging.warning(_("Project file {} exists but will not be used").format(self.projectfile))

        if read_project:
            logging.info(_("Loading existing project file {}").format(self.projectfile))

            # Try to load the project file
            subtitles : Subtitles|None = self.ReadProjectFile(self.projectfile)
            project_settings = self.GetProjectSettings()

            if subtitles:
                outputpath = outputpath or GetOutputPath(self.projectfile, subtitles.target_language)
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
                subtitles = self.LoadSubtitleFile(sourcepath)

                # Reapply project settings
                if read_project and project_settings:
                    subtitles.UpdateProjectSettings(project_settings)

            except Exception as e:
                logging.error(_("Failed to load subtitle file {}: {}").format(filepath, str(e)))
                raise

            if not subtitles or not subtitles.has_subtitles:
                raise ValueError(_("No subtitles to translate in {}").format(filepath))

            if outputpath:
                subtitles.outputpath = outputpath

            self.needs_writing = self.use_project_file

    def SaveOriginal(self, outputpath : str|None = None):
        """
        Write the original subtitles to a file
        """
        try:
            with self.lock:
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
        """ Calculate the project file path based on the source file path """
        path, ext = os.path.splitext(filepath)
        filepath = filepath if ext == '.subtrans' else f"{path}.subtrans"
        return os.path.normpath(filepath)

    def GetBackupFilepath(self, filepath : str) -> str:
        """ Get the backup file path for the project file """
        projectfile = self.GetProjectFilepath(filepath)
        return f"{projectfile}-backup"

    def LoadSubtitleFile(self, filepath : str) -> Subtitles:
        """
        Load subtitles from a file
        """
        with self.lock:
            self.subtitles = Subtitles(filepath)
            self.subtitles.LoadSubtitles()

        return self.subtitles

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

            self.subtitles.outputpath = GetOutputPath(projectfile, self.subtitles.target_language)
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
                    subtitles: Subtitles = json.load(f, cls=SubtitleDecoder)

                subtitles.Sanitise()
                self.subtitles = subtitles
                return subtitles

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

        return SettingsType({ key : value for key, value in self.subtitles.settings.items() if value })

    def UpdateProjectSettings(self, settings: SettingsType) -> None:
        """
        Replace settings if the provided dictionary has an entry with the same key
        """
        if isinstance(settings, Options):
            settings = SettingsType(settings)

        with self.lock:
            if not self.subtitles:
                return

            common_keys = settings.keys() & self.subtitles.settings.keys()
            if all(settings.get(key) == self.subtitles.settings.get(key) for key in common_keys):
                return

            self.subtitles.UpdateProjectSettings(settings)

        if self.subtitles.scenes:
            self.subtitles.UpdateOutputPath()
            self.needs_writing = self.use_project_file

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
            if save_translation and self.subtitles and translator.stop_on_error:
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

    def ReparseBatchTranslation(self, translator : SubtitleTranslator, scene_number : int, batch_number : int, line_numbers : list[int]|None = None) -> SubtitleBatch:
        """
        Reparse the translation of a batch of subtitles
        """
        batch : SubtitleBatch = self.subtitles.GetBatch(scene_number, batch_number)

        if not batch:
            raise SubtitleError(f"Unable to find batch {batch_number} in scene {scene_number}")

        if not batch.translation:
            raise SubtitleError(f"Batch {batch} is not translated")

        with self.lock:
            translator.ProcessBatchTranslation(batch, batch.translation, line_numbers=line_numbers)

            self.events.batch_translated(batch)

        return batch

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
