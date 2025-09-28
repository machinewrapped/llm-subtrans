from os import linesep
import logging
import threading
from typing import Any

from PySubtrans.Helpers.ContextHelpers import GetBatchContext
from PySubtrans.Helpers.SubtitleHelpers import MergeTranslations
from PySubtrans.Helpers.Localization import _, tr
from PySubtrans.Helpers.Text import Linearise, SanitiseSummary
from PySubtrans.Instructions import DEFAULT_TASK_TYPE, Instructions
from PySubtrans.SettingsType import SettingsType
from PySubtrans.Substitutions import Substitutions
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.SubtitleProcessor import SubtitleProcessor
from PySubtrans.SubtitleValidator import SubtitleValidator
from PySubtrans.Translation import Translation
from PySubtrans.TranslationClient import TranslationClient
from PySubtrans.TranslationParser import TranslationParser
from PySubtrans.Options import Options, SettingsType
from PySubtrans.SubtitleBatch import SubtitleBatch

from PySubtrans.SubtitleError import NoProviderError, NoTranslationError, ProviderError, SubtitleError, TranslationAbortedError, TranslationError, TranslationImpossibleError
from PySubtrans.Helpers import FormatErrorMessages
from PySubtrans.Subtitles import Subtitles
from PySubtrans.SubtitleScene import SubtitleScene, UnbatchScenes
from PySubtrans.TranslationEvents import TranslationEvents
from PySubtrans.TranslationPrompt import TranslationPrompt
from PySubtrans.TranslationProvider import TranslationProvider
from PySubtrans.TranslationRequest import StreamingCallback

class SubtitleTranslator:
    """
    Processes subtitles into scenes and batches and sends them for translation
    """
    def __init__(self, settings: Options, translation_provider: TranslationProvider, resume: bool = False):
        """
        Initialise a SubtitleTranslator with translation options
        """
        self.events = TranslationEvents()
        self.lock = threading.Lock()
        self.aborted : bool = False
        self.errors : list[str|SubtitleError] = []
        self.lines_processed : int = 0

        self.max_lines = settings.get_int('max_lines')
        self.max_history = settings.get_int('max_context_summaries')
        self.stop_on_error = settings.get_bool('stop_on_error')
        self.retry_on_error = settings.get_bool('retry_on_error')
        # self.split_on_error = options.get('autosplit_incomplete')
        self.max_summary_length = settings.get_int('max_summary_length')
        self.retranslate = settings.get_bool('retranslate')
        self.reparse = settings.get_bool('reparse')
        self.preview = settings.get_bool('preview')
        self.resume = resume and (not self.reparse and not self.retranslate)

        settings = Options(settings)

        self.instructions : Instructions = settings.GetInstructions()
        self.task_type : str = self.instructions.task_type or DEFAULT_TASK_TYPE
        self.user_prompt : str = settings.BuildUserPrompt()

        substitutions_mode = settings.get_str('substitution_mode') or Substitutions.Mode.Auto
        substitutions_list = settings.get('substitutions', {})
        if not isinstance(substitutions_list, (dict, list, str)):
            logging.warning(_("Invalid substitutions list, must be a dictionary, list or string"))
            substitutions_list = {}

        self.substitutions = Substitutions(substitutions_list, substitutions_mode)

        self.settings : SettingsType = settings.GetSettings()
        self.settings['instructions'] = self.instructions.instructions
        self.settings['retry_instructions'] = self.instructions.retry_instructions

        logging.debug(f"Translation prompt: {self.user_prompt}")

        self.translation_provider : TranslationProvider = translation_provider

        if not self.translation_provider:
            raise NoProviderError()

        try:
            self.client : TranslationClient = self.translation_provider.GetTranslationClient(self.settings)

        except Exception as e:
            raise ProviderError(_("Unable to create provider client: {error}").format(error=str(e)), translation_provider)

        if not self.client:
            raise ProviderError(_("Unable to create translation client"), translation_provider)

        self.postprocessor = SubtitleProcessor(settings) if settings.get('postprocess_translation') else None
        self.validator = SubtitleValidator(settings)

    def StopTranslating(self):
        self.aborted = True
        self.client.AbortTranslation()

    def TranslateSubtitles(self, subtitles : Subtitles):
        """
        Translate a SubtitleFile
        """
        if not subtitles:
            raise TranslationImpossibleError(_("No subtitles to translate"))

        if subtitles.scenes and self.resume:
            self._emit_info(_("Resuming translation"))

        if not subtitles.scenes:
            raise TranslationImpossibleError(_("Subtitles must be batched before translation"))

        self._emit_info(_("Translating {linecount} lines in {scenecount} scenes").format(linecount=subtitles.linecount, scenecount=subtitles.scenecount))

        self.events.preprocessed.send(self, scenes=subtitles.scenes)

        # Iterate over each subtitle scene and request translation
        for scene in subtitles.scenes:
            if self.aborted:
                break

            if self.max_lines and self.lines_processed >= self.max_lines:
                break

            if self.resume and scene.all_translated:
                self._emit_info(_("Scene {scene} already translated {linecount} lines...").format(scene=scene.number, linecount=scene.linecount))
                continue

            logging.debug(f"Translating scene {scene.number} of {subtitles.scenecount}")
            batch_numbers =[ batch.number for batch in scene.batches if not batch.translated ] if self.resume else None

            self.TranslateScene(subtitles, scene, batch_numbers=batch_numbers)

            if self.errors and self.stop_on_error:
                self._emit_error(_("Failed to translate scene {scene}... stopping translation").format(scene=scene.number))
                return

        if self.aborted:
            self._emit_info(_("Translation aborted"))
            return

        # Linearise the translated scenes
        originals, translations, untranslated = UnbatchScenes(subtitles.scenes)

        if translations:
            self._emit_info(_("Successfully translated {count} lines!").format(count=len(translations)))

        if untranslated and not self.max_lines and not self.preview:
            logging.warning(_("Failed to translate {count} lines:").format(count=len(untranslated)))
            for line in untranslated:
                self._emit_info(_("Untranslated > {number}. {text}").format(number=line.number, text=line.text))

        subtitles.originals = originals
        subtitles.translated = translations

    def TranslateScene(self, subtitles : Subtitles, scene : SubtitleScene, batch_numbers = None, line_numbers = None):
        """
        Send a scene for translation
        """
        try:
            batches = [ batch for batch in scene.batches if batch.number in batch_numbers ] if batch_numbers else scene.batches
            context = {}

            for batch in batches:
                context = GetBatchContext(subtitles, scene.number, batch.number, self.max_history)

                try:
                    self.TranslateBatch(batch, line_numbers, context)

                except TranslationImpossibleError as e:
                    # If batch has any translated lines from streaming, validate them before re-raising
                    if batch.any_translated:
                        self.validator.ValidateBatch(batch)
                    raise

                except TranslationError as e:
                    self._emit_warning(_("Error translating scene {scene} batch {batch}: {error}").format(scene=batch.scene, batch=batch.number, error=str(e)))
                    batch.errors.append(e)

                if self.aborted:
                    return

                # Notify observers the batch was translated
                self.events.batch_translated.send(self, batch=batch)

                if batch.errors:
                    self._emit_warning(_("Errors encountered translating scene {scene} batch {batch}").format(scene=batch.scene, batch=batch.number))
                    scene.errors.extend(batch.errors)
                    self.errors.extend(batch.errors)
                    if self.stop_on_error:
                        return

                if self.max_lines and self.lines_processed >= self.max_lines:
                    self._emit_info(_("Reached max_lines limit of ({lines} lines)... finishing").format(lines=self.max_lines))
                    break

            # Update the scene summary based on the best available information (we hope)
            scene.summary = self._get_best_summary([scene.summary, context.get('scene'), context.get('summary')])

            # Notify observers the scene was translated
            self.events.scene_translated.send(self, scene=scene)

        except (TranslationAbortedError, TranslationImpossibleError) as e:
            raise

    def TranslateBatch(self, batch : SubtitleBatch, line_numbers : list[int]|None, context : dict[str,Any]|None):
        """
        Send batches of subtitles for translation, building up context.
        """
        if self.aborted:
            return

        if self.reparse and batch.translation:
            self._emit_info(_("Reparsing scene {scene} batch {batch} with {count} lines...").format(scene=batch.scene, batch=batch.number, count=len(batch.originals)))
            self.ProcessBatchTranslation(batch, batch.translation, line_numbers)
            return

        if self.resume and not self.retranslate and batch.all_translated:
            self._emit_info(_("Scene {scene} batch {batch} already translated {lines} lines...").format(scene=batch.scene, batch=batch.number, lines=batch.size))
            return

        originals, context = self.PreprocessBatch(batch, context)

        logging.debug(f"Translating scene {batch.scene} batch {batch.number} with {len(originals)} lines...")

        # Build summaries context
        context['batch'] = f"Scene {batch.scene} batch {batch.number}"
        if batch.summary:
            context['summary'] = batch.summary

        instructions = self.instructions.instructions
        if not instructions:
            raise TranslationImpossibleError(_("No instructions provided for translation"))

        batch.prompt = self.client.BuildTranslationPrompt(self.user_prompt, instructions, originals, context)

        if self.preview:
            return

        # Ask the client to do the translation
        streaming_callback = self._create_streaming_callback(batch, line_numbers) if self.client.enable_streaming else None
        translation : Translation|None = self.client.RequestTranslation(batch.prompt, streaming_callback=streaming_callback)

        if (translation and translation.reached_token_limit) and not self.aborted:
            # Try again without the context to keep the tokens down
            # TODO: better to split the batch into smaller chunks
            logging.warning(_("Hit API token limit, retrying batch without context..."))
            batch.prompt.GenerateMessages(instructions, batch.originals, {})

            translation = self.client.RequestTranslation(batch.prompt, streaming_callback=streaming_callback)

        if not self.aborted:
            if not translation:
                raise TranslationError(f"Unable to translate scene {batch.scene} batch {batch.number}")

            # Process the response
            self.ProcessBatchTranslation(batch, translation, line_numbers)

            # Consider retrying if there were errors
            if batch.errors and self.retry_on_error:
                logging.warning(_("Scene {scene} batch {batch} failed validation, requesting retranslation").format(scene=batch.scene, batch=batch.number))
                self.RequestRetranslation(batch, line_numbers=line_numbers, context=context)

            # Update the context, unless it's a retranslation pass
            if not self.retranslate and not self.aborted:
                context['summary'] = self._get_best_summary([translation.summary, batch.summary])
                context['scene'] = self._get_best_summary([translation.scene, context.get('scene')])
                context['synopsis'] = translation.synopsis or context.get('synopsis', "")
                #context['names'] = translation.names or context.get('names', []) or options.get('names')
                batch.UpdateContext(context)

    def PreprocessBatch(self, batch : SubtitleBatch, context : dict[str,Any]|None = None) -> tuple[list[SubtitleLine], dict[str, Any]]:
        """
        Preprocess the batch before translation
        """
        context = context or {}
        if batch.context and (self.retranslate or self.reparse):
            # If it's a retranslation, restore context from the batch
            for key, value in batch.context.items():
                context[key] = value

        # Apply any substitutions to the input
        replacements = batch.PerformInputSubstitutions(self.substitutions)

        if replacements:
            replaced : list[str] = [f"{Linearise(k)} -> {Linearise(v)}" for k,v in replacements.items()]
            self._emit_info(_("Made substitutions in input:\n{replaced}").format(replaced=linesep.join(replaced)))
            batch.AddContext('replacements', replaced)

        # Filter out empty lines
        originals = [ line for line in batch.originals if line.text and line.text.strip() ]

        # Apply the max_lines limit
        with self.lock:
            line_count = min(self.max_lines - self.lines_processed, len(originals)) if self.max_lines else len(originals)
            self.lines_processed += line_count
            if len(originals) > line_count:
                self._emit_info(_("Truncating batch to remain within max_lines"))
                originals = originals[:line_count] if line_count > 0 else []

        return originals, context

    def ProcessBatchTranslation(self, batch : SubtitleBatch, translation : Translation, line_numbers : list[int]|None):
        """
        Attempt to extract translation from the API response
        """
        if not translation:
            raise NoTranslationError("No translation provided")

        if not translation.has_translation:
            raise TranslationError("Translation contains no translated text", translation=translation)

        logging.debug(f"Scene {batch.scene} batch {batch.number} translation:\n{translation.text}\n")

        # Apply the translation to the subtitles
        parser : TranslationParser = self.client.GetParser(self.task_type)

        parser.ProcessTranslation(translation)

        # Try to match the translations with the original lines
        translated, unmatched = parser.MatchTranslations(batch.originals)

        # Assign the translated lines to the batch
        if line_numbers:
            translated = [line for line in translated if line.number in line_numbers]

        batch._translated = MergeTranslations(batch.translated or [], translated)

        batch.translation = translation
        batch.errors = [err for err in parser.errors if isinstance(err, str) or isinstance(err, SubtitleError)]

        # Emit any warnings from the parser
        for warning in parser.warnings:
            self._emit_warning(warning)

        if batch.untranslated and not self.max_lines:
            self._emit_warning(_("Unable to match {count} lines with a source line").format(count=len(unmatched)))
            batch.AddContext('untranslated_lines', [f"{item.number}. {item.text}" for item in batch.untranslated])

        # Apply any word/phrase substitutions to the translation
        replacements = batch.PerformOutputSubstitutions(self.substitutions)

        if replacements:
            replaced = [f"{k} -> {v}" for k,v in replacements.items()]
            self._emit_info(_("Made substitutions in output:\n{replaced}").format(replaced=linesep.join(replaced)))

        # Perform substitutions on the output
        translation.PerformSubstitutions(self.substitutions)

        # Post-process the translation
        if self.postprocessor:
            batch._translated = self.postprocessor.PostprocessSubtitles(batch.translated)

            self._emit_info(_("Scene {scene} batch {batch}: {translated} lines and {untranslated} untranslated.").format(
                scene=batch.scene, 
                batch=batch.number, 
                translated=len(batch.translated or []), 
                untranslated=len(batch.untranslated or []))
                )

        if translation.summary and translation.summary.strip():
            self._emit_info(_("Summary: {summary}").format(summary=translation.summary))

    def RequestRetranslation(self, batch : SubtitleBatch, line_numbers : list[int]|None = None, context : dict[str, str]|None = None):
        """
        Ask the client to retranslate the input and correct errors
        """
        translation : Translation|None = batch.translation
        if not translation:
            raise TranslationError("No translation to retranslate")

        prompt : TranslationPrompt|None = batch.prompt
        if not prompt or not prompt.messages:
            raise TranslationError("No prompt to retranslate")

        if not self.instructions.retry_instructions:
            raise TranslationError("No retry instructions provided")

        if not translation.text:
            raise TranslationError("No translation text to retranslate", translation=translation)

        retry_instructions = self.instructions.retry_instructions
        if retry_instructions is None:
            return

        prompt.GenerateRetryPrompt(translation.text, retry_instructions, batch.errors)

        # Let's raise the temperature a little bit
        temperature = self.client.temperature or 0.0
        retry_temperature = min(temperature + 0.1, 1.0)

        retranslation : Translation|None = self.client.RequestTranslation(prompt, retry_temperature)

        if self.aborted:
            return None

        if not isinstance(retranslation, Translation):
            raise TranslationError("Retranslation is not the expected type", translation=retranslation)

        logging.debug(f"Scene {batch.scene} batch {batch.number} retranslation:\n{retranslation.text}\n")

        self.ProcessBatchTranslation(batch, retranslation, line_numbers)

        if batch.errors:
            self._emit_warning(_("Retry failed validation: {errors}").format(errors=FormatErrorMessages(batch.errors)))
        else:
            self._emit_info(_("Retry passed validation"))

    def _get_best_summary(self, candidates : list[str|None]) -> str|None:
        """
        Generate a summary of the translated subtitles
        """
        movie_name : str|None = self.settings.get_str( 'movie_name', None)
        movie_name = str(movie_name).strip() if movie_name else None
        max_length : int|None = self.max_summary_length

        for candidate in candidates:
            if candidate is None:
                continue

            sanitised = SanitiseSummary(candidate, movie_name, max_length)
            if sanitised:
                if len(sanitised) < len(candidate):
                    self._emit_info(_("Summary was truncated from {original} to {truncated} characters").format(original=len(candidate), truncated=len(sanitised)))
                return sanitised

        return None

    def _create_streaming_callback(self, batch : SubtitleBatch, line_numbers : list[int]|None) -> StreamingCallback:
        """
        Create a streaming callback that processes partial translations and emits batch_updated events
        """
        def streaming_callback(partial_translation : Translation):
            if self.aborted or not partial_translation:
                return

            try:
                # Process the partial translation (without validation)
                self._process_partial_translation(batch, partial_translation, line_numbers)

                # Emit batch_updated event with the updated batch
                self.events.batch_updated.send(self, batch=batch)

            except Exception as e:
                logging.warning(f"Error processing streaming update for scene {batch.scene} batch {batch.number}: {e}")

        return streaming_callback

    def _process_partial_translation(self, batch : SubtitleBatch, translation : Translation, line_numbers : list[int]|None):
        """
        Process a partial translation without validation (streaming updates only)
        """
        if not translation or not translation.has_translation:
            return

        # Apply the translation to the subtitles
        parser = self.client.GetParser(self.task_type)
        try:
            parser.ProcessTranslation(translation)

            # Try to match the translations with the original lines
            translated, _ = parser.MatchTranslations(batch.originals)

            # Assign the translated lines to the batch
            if line_numbers:
                translated = [line for line in translated if line.number in line_numbers]

            # Merge with existing translations (MergeTranslations is already imported at top)
            # Todo: we should use a SubtitleEditor to merge changes 
            batch.translated = MergeTranslations(batch.translated or [], translated)

            # Note: We don't set errors for partial translations to avoid false validation failures

        except Exception:
            pass

    def _emit_error(self, message : str):
        """Emit an error event"""
        self.events.error.send(self, message=message)

    def _emit_warning(self, message : str):
        """Emit a warning event"""
        self.events.warning.send(self, message=message)

    def _emit_info(self, message : str):
        """Emit an info event"""
        self.events.info.send(self, message=message)
