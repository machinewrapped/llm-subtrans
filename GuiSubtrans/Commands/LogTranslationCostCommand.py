"""Command for reporting the cumulative translation cost of a project."""
import logging

from GuiSubtrans.Command import Command
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from PySubtrans.Helpers.Localization import _


class LogTranslationCostCommand(Command):
    """Log the cumulative provider-reported translation cost after a run."""

    def __init__(self, datamodel : ProjectDataModel|None = None):
        super().__init__(datamodel)
        self.skip_undo = True
        self.is_blocking = True
        self.can_undo = False
        self.mark_project_dirty = False

    def execute(self) -> bool:
        if self.datamodel and self.datamodel.project and self.datamodel.project.subtitles:
            cost = self.datamodel.project.subtitles.translation_cost
            if cost is not None:
                logging.info(_("Translation cost: ${cost:.4f}").format(cost=cost))

        return True
