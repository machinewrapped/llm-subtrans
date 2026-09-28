from GuiSubtrans.Command import Command
from GuiSubtrans.CommandQueue import CommandQueue
from GuiSubtrans.Commands.StartTranslationCommand import StartTranslationCommand
from GuiSubtrans.GuiSubtitleTestCase import GuiSubtitleTestCase
from GuiSubtrans.ProjectActions import ProjectActions
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from GuiSubtrans.ProjectSelection import ProjectSelection, SelectionBatch, SelectionLine, SelectionScene


class CapturingCommandQueue(CommandQueue):
    """Command queue that records queued commands instead of executing them."""
    def __init__(self) -> None:
        super().__init__(None)
        self.captured : list[Command] = []

    def AddCommand(self, command : Command, datamodel : ProjectDataModel|None = None, callback = None, undo_callback = None):
        self.captured.append(command)


class TranslateSelectionTests(GuiSubtitleTestCase):
    """Test how ProjectActions.TranslateSelection maps a selection to scenes, batches and lines."""

    def _translate(self, selection : ProjectSelection) -> dict:
        datamodel, _subtitles = self.create_datamodel_from_line_counts([[2, 2], [2, 2]])
        queue = CapturingCommandQueue()
        actions = ProjectActions(queue, datamodel)

        actions.TranslateSelection(selection)

        self.assertLoggedEqual("commands queued", 1, len(queue.captured))
        command = queue.captured[0]
        self.assertLoggedIsInstance("queued command", command, StartTranslationCommand)
        return command.scenes if isinstance(command, StartTranslationCommand) else {}

    def test_scene_and_batch_from_another_scene(self) -> None:
        selection = ProjectSelection()
        selection.scenes[1] = SelectionScene(1, selected=True)
        selection.batches[(1, 1)] = SelectionBatch((1, 1), selected=False)
        selection.batches[(1, 2)] = SelectionBatch((1, 2), selected=False)
        selection.scenes[2] = SelectionScene(2, selected=False)
        selection.batches[(2, 1)] = SelectionBatch((2, 1), selected=True)

        scenes = self._translate(selection)

        self.assertLoggedEqual("selected scene has no batch restriction", {}, scenes.get(1))
        self.assertLoggedEqual("scene 2 is limited to the selected batch", { 'batches' : [1] }, scenes.get(2))

    def test_selected_lines_take_precedence(self) -> None:
        selection = ProjectSelection()
        selection.scenes[1] = SelectionScene(1, selected=True)
        selection.batches[(1, 1)] = SelectionBatch((1, 1), selected=False)
        selection.batches[(1, 2)] = SelectionBatch((1, 2), selected=False)
        selection.AddSelectedLines([SelectionLine(1, 2, 3, True), SelectionLine(1, 2, 4, True)])

        scenes = self._translate(selection)

        self.assertLoggedSequenceEqual("scenes to translate", [1], sorted(scenes.keys()))
        self.assertLoggedEqual("only the selected lines", { 'batches' : [2], 'lines' : [3, 4] }, scenes.get(1))
