import json

from GuiSubtrans.Commands.StartTranslationCommand import StartTranslationCommand
from GuiSubtrans.Commands.TranslateSceneCommand import TranslateSceneCommand
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from PySubtrans.Helpers.TestCases import BuildSubtitlesFromLineCounts, SubtitleTestCase
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.Subtitles import Subtitles
from PySubtrans.SubtitleSerialisation import SubtitleDecoder, SubtitleEncoder
from PySubtrans.ValidationError import LineTooLongError


class StartTranslationResumeTests(SubtitleTestCase):
    """Resume must schedule saved failures through the GUI command interface."""

    def test_resume_schedules_invalid_batches_and_reuses_valid_batches(self) -> None:
        """Cover project, scene, and batch filtering in both scheduling modes."""
        cases = [
            ([["invalid"]], [(1, [1])]),
            ([["invalid"], ["pending"]], [(1, [1]), (2, None)]),
            ([["valid"], ["valid", "invalid", "pending"]], [(2, [2, 3])]),
            ([["valid"], ["valid"]], []),
        ]
        self.options.add("provider", None)
        self.options.add("autosave", False)

        for states, expected in cases:
            for multithreaded in [False, True]:
                with self.subTest(states=states, multithreaded=multithreaded):
                    subtitles = BuildSubtitlesFromLineCounts(
                        [[1] * len(scene) for scene in states]
                    )
                    for scene, batch_states in zip(subtitles.scenes, states):
                        for batch, state in zip(scene.batches, batch_states):
                            if state == "pending":
                                continue
                            batch.translated = [
                                SubtitleLine(line) for line in batch.originals
                            ]
                            batch.translated[0].text = (
                                "Saved translation" if state == "valid" else "x" * 80
                            )
                            batch.originals[0].translated = batch.translated[0]
                            if state == "invalid":
                                batch.errors = [
                                    LineTooLongError(
                                        "Synthetic validation error",
                                        lines=batch.translated,
                                    )
                                ]

                    serialized = json.dumps(subtitles, cls=SubtitleEncoder)
                    reloaded_subtitles : Subtitles = json.loads(
                        serialized, cls=SubtitleDecoder
                    )
                    self.assertLoggedIsInstance(
                        "Subtitles reload", reloaded_subtitles, Subtitles
                    )
                    for scene, batch_states in zip(reloaded_subtitles.scenes, states):
                        for batch, state in zip(scene.batches, batch_states):
                            self.assertLoggedEqual(
                                "Saved validation errors survive reload",
                                1 if state == "invalid" else 0,
                                len(batch.errors),
                            )

                    reloaded = self.create_subtitle_project(reloaded_subtitles)
                    reloaded.needs_writing = False
                    datamodel = ProjectDataModel(reloaded, self.options.GetSettings())
                    command = StartTranslationCommand(
                        datamodel, resume=True, multithreaded=multithreaded
                    )
                    self.assertLoggedTrue(
                        "Resume scheduling succeeds", command.execute()
                    )

                    scheduled = []
                    pending_commands = list(command.commands_to_queue)
                    while pending_commands:
                        queued = pending_commands.pop(0)
                        if isinstance(queued, TranslateSceneCommand):
                            scheduled.append(
                                (queued.scene_number, queued.batch_numbers)
                            )
                            self.assertLoggedTrue(
                                "Queued translation preserves resume mode",
                                queued.resume,
                            )
                        pending_commands.extend(queued.commands_to_queue)

                    self.assertLoggedEqual(
                        "Only invalid and unfinished batches are scheduled",
                        expected,
                        scheduled,
                    )
