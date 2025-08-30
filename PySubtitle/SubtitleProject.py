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
from PySubtitle.SubtitleFormatRegistry import SubtitleFormatRegistry
from PySubtitle.SubtitleFileHandler import SubtitleFileHandler
from PySubtitle.Formats.VoidFileHandler import VoidFileHandler

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
    def __init__(self, options : Options):
        """
        Initialise an empty project. Can be initialised from a project file or a subtitle file,
        or manually configured by assigning a SubtitleFile and updating settings if necessary.
        
        :param options: Only used to set the project mode
        """
        self.subtitles: Subtitles = Subtitles(VoidFileHandler())
        self.events = TranslationEvents()
        self.projectfile : str|None = None
        self.read_project : bool = False
        self.write_project : bool = False
        self.needs_writing : bool = False
        self.lock = threading.RLock()

        self._update_project_mode(options)

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
            return True if self.subtitles and self.subtitles.translated else False

    def InitialiseProject(
        self,
        filepath: str,
        outputpath: str | None = None,
        reload_subtitles: bool = False,
    ):
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

        if self.projectfile == filepath and not self.read_project:
            self.read_project = True
            self.write_project = True

        if self.read_project and not project_file_exists:
            logging.info(_("Project file {} does not exist").format(self.projectfile))
            self.read_project = False
            self.load_subtitles = True

        if self.read_project:
            # Try to load the project file
            subtitles : Subtitles|None = self.ReadProjectFile(self.projectfile)
            project_settings = self.GetProjectSettings()

            if subtitles:
                outputpath = outputpath or GetOutputPath(self.projectfile, subtitles.target_language)
                sourcepath = subtitles.sourcepath if subtitles.sourcepath else sourcepath               
                logging.info(_("Project file loaded"))

                if subtitles.scenes:
                    self.load_subtitles = reload_subtitles
                    if self.load_subtitles:
                        logging.info(_("Reloading subtitles from the source file"))

                else:
                    logging.error(_("Unable to read project file, starting afresh"))
                    self.load_subtitles = True

        if self.load_subtitles:
            try:
                # (re)load the source subtitle file if required
                subtitles = self.LoadSubtitleFile(sourcepath)

                # Reapply project settings
                if self.read_project and project_settings:
                    subtitles.UpdateProjectSettings(project_settings)

            except Exception as e:
                logging.error(_("Failed to load subtitle file {}: {}").format(filepath, str(e)))
                raise

            if not subtitles or not subtitles.has_subtitles:
                raise ValueError(_("No subtitles to translate in {}").format(filepath))

            if outputpath:
                subtitles.outputpath = outputpath

        self.needs_writing = self.write_project

    def SaveOriginal(self, outputpath : str|None = None):
        """
        Write the original subtitles to a file
        """
        try:
            with self.lock:
                #TODO: detect the format from the output path and instantiate an appopriate file handler
                self.subtitles.SaveOriginal(outputpath)

        except Exception as e:
            logging.error(_("Unable to save original subtitles: {}").format(e))

    def SaveTranslation(self, outputpath : str|None = None):
        """
        Write output file
        """
        try:
            with self.lock:
                #TODO: detect the format from the output path and instantiate an appopriate file handler
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

    def LoadSubtitleFile(self, filepath: str) -> Subtitles:
        """Load subtitles from a file, auto-detecting the format by extension"""
        extension = os.path.splitext(filepath)[1]
        handler: SubtitleFileHandler = SubtitleFormatRegistry.create_handler(extension)
        with self.lock:
            self.subtitles = Subtitles(handler, filepath)
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

            if projectfile and not self.write_project:
                self.write_project = True
                self.read_project = True

            if not projectfile:
                projectfile = self.projectfile
            elif projectfile and not self.projectfile:
                self.projectfile = self.GetProjectFilepath(projectfile)

            if not projectfile:
                raise Exception("No file path provided")

            # output translations in the same directory as the project
            self._update_output_path(projectfile)
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

                if subtitles.outputpath:
                    ext = os.path.splitext(subtitles.outputpath)[1]
                    try:
                        subtitles.file_handler = SubtitleFormatRegistry.create_handler(ext)
                    except ValueError:
                        logging.warning(_("Unknown file type {extension}").format(extension = ext))

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
            self.needs_writing = True

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
        Use the translation provider to translate a project
        """
        if not self.subtitles:
            raise Exception("No subtitles to translate")

        # Prime new project files
        self.UpdateProjectFile()

        try:
            translator.events.preprocessed += self._on_preprocessed # type: ignore
            translator.events.batch_translated += self._on_batch_translated # type: ignore
            translator.events.scene_translated += self._on_scene_translated # type: ignore

            translator.TranslateSubtitles(self.subtitles)

            translator.events.preprocessed -= self._on_preprocessed # type: ignore
            translator.events.batch_translated -= self._on_batch_translated # type: ignore
            translator.events.scene_translated -= self._on_scene_translated # type: ignore

            if self.save_subtitles and not translator.aborted:
                self.SaveTranslation()

        except TranslationAbortedError:
            logging.info(_("Translation aborted"))

        except Exception as e:
            if self.subtitles and self.save_subtitles and translator.stop_on_error:
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

            if self.save_subtitles and not translator.aborted:
                self.SaveTranslation()

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

    def _update_project_mode(self, options : Options) -> None:
        """
        Update the project mode based on the settings... yes, this is a dumb system
        """
        project_mode = options.get_str('project')
        if project_mode:
            project_mode = project_mode.lower()

        self.read_project = project_mode in ["true", "read", "resume", "retranslate", "reparse"]
        self.write_project = project_mode in ["true", "write", "preview", "resume", "retranslate", "reparse"]
        self.load_subtitles = project_mode is None or project_mode in ["true", "write", "reload", "preview"]
        self.save_subtitles = project_mode not in ['preview', 'test']

        options.add("preview", project_mode in ["preview"])
        options.add("resume", project_mode in ["resume"])
        options.add("reparse", project_mode in ["reparse"])
        options.add("retranslate", project_mode in ["retranslate"])

    def _on_preprocessed(self, scenes) -> None:
        logging.debug("Pre-processing finished")
        self.needs_writing = self.write_project
        self.events.preprocessed(scenes)

    def _on_batch_translated(self, batch) -> None:
        logging.debug("Batch translated")
        self.needs_writing = self.write_project
        self.events.batch_translated(batch)

    def _on_scene_translated(self, scene) -> None:
        logging.debug("Scene translated")
        self.needs_writing = self.write_project
        self.events.scene_translated(scene)

    def _update_output_path(self, projectfile):
        extension : str = ".srt"  # Default fallback
        if self.subtitles.outputpath:
            extension = os.path.splitext(self.subtitles.outputpath)[1]
            if not extension and self.subtitles.sourcepath:
                extension = os.path.splitext(self.subtitles.sourcepath)[1]
                
        self.subtitles.outputpath = GetOutputPath(projectfile, self.subtitles.target_language, extension)

