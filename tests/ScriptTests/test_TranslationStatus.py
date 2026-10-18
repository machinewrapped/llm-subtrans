import logging
from unittest.mock import patch

from PySubtrans.Helpers.TestCases import (
    BuildSubtitlesFromLineCounts,
    DummyProvider,
    SubtitleTestCase,
)
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.SubtitleTranslator import SubtitleTranslator
from PySubtrans.ValidationError import LineTooLongError
from scripts.subtrans_common import LogTranslationStatus, TokenUsage, TranslateProject


class TranslationStatusTests(SubtitleTestCase):
    """CLI completion reports must distinguish line coverage from success."""

    def test_saved_validation_errors_are_not_reported_as_complete(self) -> None:
        """A full set of rejected translations must produce a warning status."""
        project = self.CreateRejectedProject()

        self.assertLoggedTrue(
            "Rejected translations still cover all lines", project.all_translated
        )
        with self.assertLogs(level=logging.INFO) as captured:
            LogTranslationStatus(project)

        self.assertLoggedEqual("One final status is emitted", 1, len(captured.records))
        self.assertLoggedEqual(
            "Invalid translation status is a warning",
            logging.WARNING,
            captured.records[0].levelno,
        )

    def test_validation_warnings_do_not_block_completion(self) -> None:
        """A run whose only issues are warnings completes, with a separate warning summary."""
        project = self.CreateRejectedProject()
        batch = project.subtitles.scenes[0].batches[0]
        batch.warnings = batch.errors
        batch.errors = []

        with self.assertLogs(level=logging.INFO) as captured:
            LogTranslationStatus(project)

        self.assertLoggedEqual(
            "Status and warning summary levels",
            [logging.INFO, logging.WARNING],
            [record.levelno for record in captured.records],
        )

    def test_token_usage_is_logged_for_every_outcome(self) -> None:
        """Usage and cost are reported after failures and previews as well as successes."""
        for preview, has_error in [(False, False), (False, True), (True, False), (True, True)]:
            with self.subTest(preview=preview, has_error=has_error):
                project = self.CreateRejectedProject()
                token_usage = TokenUsage(prompt_tokens=100, output_tokens=50, cost=0.25)

                with self.assertLogs(level=logging.INFO) as captured:
                    LogTranslationStatus(project, preview=preview, has_error=has_error, token_usage=token_usage)

                self.assertLoggedEqual(
                    "Status followed by usage and cost", 3, len(captured.records)
                )

    def test_resume_and_preview_report_the_final_outcome(self) -> None:
        """Real validation failure, successful correction, and preview retain distinct outcomes."""
        for preview, response, expected_level in [
            (False, "y" * 80, logging.WARNING),
            (False, "Corrected translation", logging.INFO),
            (True, "Unused translation", logging.INFO),
        ]:
            with self.subTest(preview=preview, expected_level=expected_level):
                project = self.CreateRejectedProject()
                batch = project.subtitles.scenes[0].batches[0]
                if preview:
                    batch.translated = []
                    batch.errors = []
                    batch.originals[0].translated = None
                    project.subtitles.translated = []

                self.options.add("preview", preview)
                self.options.add("max_characters", 40)
                self.options.add("autosplit_on_error", False)
                # Long lines must fail validation for the rejected case
                self.options.add("warnings_as_errors", True)
                provider = DummyProvider(
                    {
                        "response_map": {
                            "Translate scene 1 batch 1": f"#{batch.originals[0].number}\nOriginal>\n{batch.originals[0].text}\nTranslation>\n{response}",
                        }
                    }
                )
                translator = SubtitleTranslator(self.options, provider, resume=True)

                with patch(
                    "scripts.subtrans_common.init_translator", return_value=translator
                ):
                    with self.assertLogs(level=logging.INFO) as captured:
                        TranslateProject(project, self.options, preview=preview)

                self.assertLoggedEqual(
                    "Final CLI status level",
                    expected_level,
                    captured.records[-1].levelno,
                )
                self.assertLoggedEqual(
                    "Validation errors propagate to the run",
                    1 if expected_level == logging.WARNING else 0,
                    len(translator.errors),
                )
                if preview:
                    self.assertLoggedEqual(
                        "Preview leaves translations empty", [], batch.translated
                    )
                else:
                    self.assertLoggedEqual(
                        "Resume replaces the saved translation",
                        response,
                        batch.translated[0].text,
                    )

    def CreateRejectedProject(self) -> SubtitleProject:
        """Build a synthetic project with complete but rejected translations."""
        subtitles = BuildSubtitlesFromLineCounts([[1]])
        subtitles.UpdateSettings(
            SettingsType(
                {
                    "movie_name": "Example story",
                    "description": "A synthetic translation test.",
                    "names": ["Example character"],
                }
            )
        )
        batch = subtitles.scenes[0].batches[0]
        batch.translated = [SubtitleLine(batch.originals[0])]
        batch.translated[0].text = "x" * 80
        batch.originals[0].translated = batch.translated[0]
        batch.errors = [
            LineTooLongError("Synthetic validation error", lines=batch.translated)
        ]
        subtitles.translated = batch.translated
        return self.create_subtitle_project(subtitles)
