import logging
from collections.abc import Callable

from PySide6.QtCore import Qt, QObject, Signal, Slot, QThreadPool, QRecursiveMutex, QMutexLocker

from GuiSubtrans.Command import Command
from GuiSubtrans.ProjectDataModel import ProjectDataModel
from PySubtrans.Helpers.Localization import _

#############################################################

class ClearCommandQueue(Command):
    """
    Pseudo-command to clear the command queue
    """
    def __init__(self, datamodel: ProjectDataModel|None = None):
        super().__init__(datamodel)

    def execute(self) -> bool:
        logging.info("Terminating command queue...")
        return True

#############################################################

class CommandQueue(QObject):
    """
    Execute commands on a background thread
    """
    commandAdded = Signal(object)
    commandStarted = Signal(object)
    commandExecuted = Signal(object)
    commandUndone = Signal(object)

    def __init__(self, parent):
        super().__init__(parent)

        self.logger = logging.getLogger("CommandQueue")

        self.queue : list[Command] = []
        self.undo_stack : list[Command] = []
        self.redo_stack : list[Command] = []

        self.mutex = QRecursiveMutex()

        self.command_pool = QThreadPool(self)

        self.SetMaxThreadCount(1)

    def SetMaxThreadCount(self, count):
        """
        Maximum number of worker threads
        """
        self.command_pool.setMaxThreadCount(count)

    @property
    def queue_size(self) -> int:
        """
        Number of commands in the queue
        """
        with QMutexLocker(self.mutex):
            return len(self.queue)

    @property
    def has_commands(self) -> bool:
        """
        True if the queue has any commands
        """
        with QMutexLocker(self.mutex):
            return len(self.queue) > 0

    @property
    def has_running_commands(self) -> bool:
        """
        True if the queue has any commands that are currently running
        """
        with QMutexLocker(self.mutex):
            return any( command.started for command in self.queue )

    @property
    def has_blocking_commands(self) -> bool:
        """
        True if the queue has any commands that are blocking
        """
        with QMutexLocker(self.mutex):
            return any( command.is_blocking for command in self.queue )

    @property
    def can_undo(self) -> bool:
        """
        True if there are any undoable commands in the undo stack
        """
        with QMutexLocker(self.mutex):
            return len(self.undo_stack) > 0 and self.undo_stack[-1].can_undo

    @property
    def can_redo(self) -> bool:
        """
        True if there are any commands in the redo stack
        """
        with QMutexLocker(self.mutex):
            return len(self.redo_stack) > 0

    @property
    def undoable_command_text(self) -> str|None:
        with QMutexLocker(self.mutex):
            if self.undo_stack:
                return _("Can undo {command}").format(command=type(self.undo_stack[-1]).__name__)
            return None

    @property
    def redoable_command_text(self) -> str|None:
        with QMutexLocker(self.mutex):
            if self.redo_stack:
                return _("Can redo {command}").format(command=type(self.redo_stack[-1]).__name__)
            return None

    def Stop(self):
        """
        Shut the background thread down
        """
        if self.has_commands:
            self._clear_command_queue()

        self.command_pool.waitForDone()

    def AddCommand(self, command: Command, datamodel: ProjectDataModel|None = None, callback: Callable|None = None, undo_callback: Callable|None = None):
        """
        Add a command to the command queue, with optional callbacks for completion/undo events
        """
        if not isinstance(command, Command):
            raise ValueError(f"Issued a command that is not a Command ({type(command).__name__})")

        self.logger.debug(f"Adding a {type(command).__name__} command to the queue")
        command.setParent(self)

        with QMutexLocker(self.mutex):
            if isinstance(command, ClearCommandQueue):
                command.execute()
                self._clear_command_queue()
            else:
                self.commandAdded.emit(command)
                self._queue_command(command, datamodel, callback, undo_callback)
                self.ClearRedoStack()

        self._start_command_queue()

    def ExecuteCommand(self, command: Command):
        """
        Execute a command immediately, bypassing the queue
        """
        if not isinstance(command, Command):
            raise ValueError(f"Issued a command that is not a Command ({type(command).__name__})")

        self.logger.debug(f"Executing a {type(command).__name__} command")
        command.setParent(self)

        try:
            with QMutexLocker(self.mutex):
                command.started = True
                command.succeeded = command.execute()

                # Mark the project as dirty if the command modified it
                if command.succeeded and command.mark_project_dirty and command.datamodel and command.datamodel.project:
                    command.datamodel.project.needs_writing = True

                if command.succeeded and not command.skip_undo:
                    self.undo_stack.append(command)
                    self.ClearRedoStack()

                if command.succeeded and not command.can_undo:
                    self.ClearUndoStack()

            command.execute_callback()

            self.commandExecuted.emit(command)
            return True

        except Exception as e:
            self.logger.error(f"Error executing {type(command).__name__}: {str(e)}")
            command.succeeded = False
            return False

    def UndoLastCommand(self):
        """
        Undo the last command in the undo stack
        """
        with QMutexLocker(self.mutex):
            command = self.undo_stack.pop()
            if not command.can_undo:
                self.logger.error(f"Cannot undo the last {type(command).__name__} command")
                return

            self.redo_stack.append(command)

        self.logger.info(f"Undoing {type(command).__name__}")

        command.undo()

        command.execute_undo_callback()

        command.started = False

        self.commandUndone.emit(command)

    def RedoLastCommand(self):
        """
        Redo the last command in the redo stack
        """
        with QMutexLocker(self.mutex):
            command = self.redo_stack.pop()
            if not command:
                self.logger.warning("No commands to redo")
                return

            self._queue_command(command)

        self.logger.info(f"Redoing {type(command).__name__}")
        self.commandAdded.emit(command)
        self._start_command_queue()

    def Contains(self, command_type: type|None = None, type_list : list[type]|None = None):
        """
        Check if the queue contains a command type(s)
        """
        if not command_type and not type_list:
            raise ValueError("Specify a command type or a list of command types")

        if type_list:
            if any( self.Contains(type) for type in type_list ):
                return True

        with QMutexLocker(self.mutex):
            return command_type and any( [ isinstance(command, command_type) ] for command in self.queue )

    def ClearUndoStack(self):
        """
        Clear the undo stack
        """
        with QMutexLocker(self.mutex):
            for command in self.undo_stack:
                command.deleteLater()
            for command in self.redo_stack:
                command.deleteLater()

            self.undo_stack = []
            self.redo_stack = []

    def ClearRedoStack(self):
        """
        Clear the redo stack
        """
        with QMutexLocker(self.mutex):
            for command in self.redo_stack:
                command.deleteLater()

            self.redo_stack = []

    @Slot(Command)
    def _on_command_started(self, command: Command):
        """
        Handle command start events
        """
        command.commandStarted.disconnect(self._on_command_started)
        if command.succeeded is None:
            self.commandStarted.emit(command)

    @Slot(Command)
    def _on_command_executed(self, command: Command):
        """
        Handle command callbacks, and queuing further actions
        """
        command.commandCompleted.disconnect(self._on_command_executed)

        if not command.aborted:
            self.logger.debug(f"A {type(command).__name__} command was completed")

            command.execute_callback()

        with QMutexLocker(self.mutex):
            if command.succeeded and not command.skip_undo:
                self.undo_stack.append(command)
            self.queue.remove(command)

        if command.succeeded and not command.can_undo:
            self.ClearUndoStack()

        self.commandExecuted.emit(command)

        if command.aborted or command.terminal:
            return

        if command.commands_to_queue:
            with QMutexLocker(self.mutex):
                for queued_command in command.commands_to_queue:
                    self._queue_command(queued_command, command.datamodel)

            for queued_command in command.commands_to_queue:
                self.commandAdded.emit(queued_command)

        self._start_command_queue()

    def _queue_command(self, command: Command, datamodel: ProjectDataModel|None = None, callback: Callable|None = None, undo_callback: Callable|None = None):
        """
        Add a command to the worker thread queue
        """
        if datamodel:
            command.SetDataModel(datamodel)
        if callback:
            command.SetCallback(callback)
        if undo_callback:
            command.SetUndoCallback(undo_callback)

        command.setAutoDelete(False)
        command.commandStarted.connect(self._on_command_started, Qt.ConnectionType.QueuedConnection)
        command.commandCompleted.connect(self._on_command_executed, Qt.ConnectionType.QueuedConnection)
        command.started = False
        command.queued = True

        self.queue.append(command)

    def _start_command_queue(self):
        """
        Start the command queue
        """
        if not self.queue:
            return

        self.logger.debug(f"Starting command queue")

        with QMutexLocker(self.mutex):
            for command in self.queue:
                if command.queued and (not command.is_blocking or not self.has_running_commands):
                    command.queued = False
                    self.command_pool.start(command)

                if command.is_blocking:
                    break

    def _clear_command_queue(self):
        """
        Abort any running commands and clear the command queue
        """
        self.logger.debug(f"Clearing command queue")

        with QMutexLocker(self.mutex):
            # Remove commands that haven't been started
            self.queue = [command for command in self.queue if command.started]
            commands_to_abort = list(self.queue)

        # Abort the remaining commands
        for command in commands_to_abort:
            command.Abort()

