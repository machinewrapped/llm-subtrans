from unittest.mock import Mock

from GuiSubtrans.GuiInterface import GuiInterface
from GuiSubtrans.GuiSubtitleTestCase import GuiSubtitleTestCase
from GuiSubtrans.MainToolbar import MainToolbar
from GuiSubtrans.ProjectActions import ProjectActions
from PySubtrans.SubtitleError import LineTooLongError
from PySubtrans.SubtitleLine import SubtitleLine


class MainToolbarResumeTests(GuiSubtitleTestCase):
    """Resume buttons must stay available for translations with saved errors."""

    def test_resume_buttons_follow_translation_completion(self) -> None:
        """Keep failed batches resumable and disable genuinely completed projects."""
        self.options.add("provider", None)
        datamodel, subtitles = self.create_datamodel_from_line_counts([[1]])
        batch = subtitles.scenes[0].batches[0]
        gui = Mock(spec=GuiInterface)
        gui.GetDataModel.return_value = datamodel
        gui.GetActionHandler.return_value = Mock(spec=ProjectActions)
        toolbar = MainToolbar(gui)
        action_names = ["Start Translating", "Start Translating Fast"]

        try:
            for state, expected_enabled in [
                ("pending", True),
                ("invalid", True),
                ("valid", False),
            ]:
                with self.subTest(state=state):
                    if state != "pending":
                        batch.translated = [SubtitleLine(batch.originals[0])]
                        batch.errors = (
                            [LineTooLongError("Synthetic validation error")]
                            if state == "invalid"
                            else []
                        )

                    toolbar.SetActionsEnabled(action_names, True)
                    toolbar.UpdateTranslateButtons()

                    for action_name in action_names:
                        self.assertLoggedEqual(
                            "Resume action availability",
                            expected_enabled,
                            toolbar.GetAction(action_name).isEnabled(),
                        )
        finally:
            toolbar.deleteLater()
