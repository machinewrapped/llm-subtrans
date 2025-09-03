from collections.abc import Callable

from PySide6.QtWidgets import QToolBar, QStyle, QApplication
from PySide6.QtCore import Qt, SignalInstance, QCoreApplication
from PySide6.QtGui import QAction, QIcon
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtCore import QByteArray
from PySide6.QtGui import QPainter, QPixmap

from GUI.CommandQueue import CommandQueue
from GUI.GuiInterface import GuiInterface
from GUI.ProjectActions import ProjectActions
from GUI.ProjectDataModel import ProjectDataModel
from GUI.Commands.StartTranslationCommand import StartTranslationCommand
from GUI.Commands.TranslateSceneCommand import TranslateSceneCommand
from PySubtitle.Helpers.Localization import _
from PySubtitle.Helpers.Resources import GetResourcePath

class MainToolbar(QToolBar):
    """
    Main toolbar for the application
    """
    _action_groups = [
        ["Load Subtitles", "Save Project"],
        ["Start Translating", "Start Translating Fast", "Stop Translating"],
        ["Undo", "Redo"],
        ["Settings"],
        ["About", "Quit"]
        ]
    
    _action_tooltips = {
        'Quit': { 'tooltip': _('Exit Program') },
        'Load Subtitles':
        {
            'tooltip': _('Load project/translation (Hold shift to reload subtitles)'), 
            'shift_tooltip': _('Load project/translation (reload subtitles)')
        },
        'Save Project':
        {
            'tooltip': _('Save project/translation (Hold shift to save as...)'), 
            'shift_tooltip': _('Save project/translation as...')
        },
        'Settings': { 'tooltip': _('Settings') },
        'Start Translating':
        {
            'tooltip': _('Start Translating (hold shift to retranslate)'),
            'shift_tooltip': _('Start retranslating')
        },
        'Start Translating Fast':
        {
            'tooltip': _('Start translating on multiple threads (fast but unsafe)'),
            'shift_tooltip': _('Start retranslating on multiple threads')
        },
        'Stop Translating': {'tooltip': _('Stop translation')},
        'Undo': {'tooltip': _('Undo last action')},
        'Redo': {'tooltip': _('Redo last undone action')},
        'About': {'tooltip': _('About this program')}
    }

    def __init__(self,  gui_interface : GuiInterface):
        super().__init__(_("Main Toolbar"))

        self.gui : GuiInterface = gui_interface

        self._actions : dict[str, QAction] = {}

        self._enabled_icons : dict[str, QIcon] = {}
        self._disabled_icons : dict[str, QIcon] = {}
        
        self._shift_pressed : bool = False

        # Subscribe to UI language changes
        self.gui.uiLanguageChanged.connect(self.UpdateUiLanguage, Qt.ConnectionType.QueuedConnection)
        
        # Install global event filter to capture shift key events
        application : QCoreApplication|None = QApplication.instance()
        if application:
            application.installEventFilter(self)

        self.DefineActions()
        self.AddActionGroups()

        self.setMovable(False)

    def UpdateToolbar(self):
        """
        Update the toolbar
        """
        self.UpdateBusyStatus()
        self.UpdateSaveButton()
        self.UpdateTranslateButtons()
        self.UpdateTooltips()

    def UpdateUiLanguage(self):
        """Recreate actions/labels after language change."""
        # Remove existing actions and rebuild with translated labels
        for action in list(self.actions()):
            self.removeAction(action)
        self.clear()
        self.DefineActions()
        self.AddActionGroups()
        self.UpdateToolbar()

    def GetAction(self, name : str) -> QAction:
        return self._actions[name]

    def GetActionList(self, names : list[str]) -> list[QAction]:
        return [ self.GetAction(name) for name in names ]

    def AddActionGroups(self):
        for group in self._action_groups:
            if group != self._action_groups[0]:
                self.addSeparator()

            actions = self.GetActionList(group)
            for action in actions:
                self.addAction(action)

    def DefineActions(self):
        """
        Define the supported actions
        """
        self._actions = {}
        action_handler : ProjectActions = self.gui.GetActionHandler()
        self.DefineAction('Quit', action_handler.exitProgram, self._icon_file('quit'), 'Ctrl+W')
        self.DefineAction('Load Subtitles', action_handler.LoadProject, self._icon_file('load_subtitles'), 'Ctrl+O')
        self.DefineAction('Save Project', action_handler.SaveProject, self._icon_file('save_project'), 'Ctrl+S')
        self.DefineAction('Settings', action_handler.showSettings, self._icon_file('settings'), 'Ctrl+?')
        self.DefineAction('Start Translating', action_handler.StartTranslating, self._icon_file('start_translating'), 'Ctrl+T')
        self.DefineAction('Start Translating Fast', action_handler.StartTranslatingFast, self._icon_file('start_translating_fast'), None)
        self.DefineAction('Stop Translating', action_handler.StopTranslating, self._icon_file('stop_translating'), 'Esc')
        self.DefineAction('Undo', action_handler.UndoLastCommand, self._icon_file('undo'), 'Ctrl+Z')
        self.DefineAction('Redo', action_handler.RedoLastCommand, self._icon_file('redo'), 'Ctrl+Shift+Z')
        self.DefineAction('About', action_handler.showAboutDialog, self._icon_file('about'))

    def DefineAction(self, name : str, function : Callable[..., None]|SignalInstance, icon : str|QIcon|None = None, shortcut : str|None = None, tooltip : str|None =None):
        """
        Define an action with a name, function, icon, shortcut, and tooltip.
        """
        # Keep English name as key; show localized text
        action = QAction(_(name))
        action.triggered.connect(function)

        if icon:
            if isinstance(icon, QIcon):
                pass  # Already a QIcon, no need to convert
            elif isinstance(icon, QStyle.StandardPixmap):
                icon = QApplication.style().standardIcon(icon)
            else:
                self._enabled_icons[name] = QIcon(icon)
                self._disabled_icons[name] = _create_disabled_icon(icon)
                icon = self._enabled_icons[name]

            action.setIcon(icon)

        if shortcut:
            action.setShortcut(shortcut)

        # Set initial tooltip based on current shift state
        self._update_action_tooltip(action, name, shortcut)

        self._actions[name] = action

    def _get_tooltip_for_action(self, name : str, use_shift_tooltip : bool = False) -> str|None:
        """
        Get the appropriate tooltip for an action based on shift state
        """
        tooltip_config = self._action_tooltips.get(name)
        if not tooltip_config:
            return None

        tooltip_text = None
        if use_shift_tooltip:
            tooltip_text = tooltip_config.get('shift_tooltip')

        if not tooltip_text:
            tooltip_text = tooltip_config.get('tooltip')

        return _(tooltip_text) if tooltip_text else None

    def _update_action_tooltip(self, action : QAction, name : str, shortcut : str|None):
        """
        Update an action's tooltip based on current shift state
        """
        tooltip = self._get_tooltip_for_action(name, self._shift_pressed)
        if tooltip:
            formatted_tooltip = f"{tooltip} ({shortcut})" if shortcut else tooltip
            action.setToolTip(formatted_tooltip)

    def EnableActions(self, action_list : list[str]):
        """
        Enable a list of commands
        """
        for name in action_list:
            action = self._actions.get(name)
            if action:
                action.setEnabled(True)
                if name in self._enabled_icons:
                    action.setIcon(self._enabled_icons[name])

    def DisableActions(self, action_list : list[str]):
        """
        Disable a list of commands
        """
        for name in action_list:
            action = self._actions.get(name)
            if action:
                action.setEnabled(False)
                if name in self._disabled_icons:
                    action.setIcon(self._disabled_icons[name])

    def SetActionsEnabled(self, action_list : list[str], enabled : bool):
        """
        Enable or disable a list of commands
        """
        icon_set : dict[str, QIcon] = self._enabled_icons if enabled else self._disabled_icons
        for name in action_list:
            action = self._actions.get(name)
            if action:
                action.setEnabled(enabled)
                if name in icon_set:
                    action.setIcon(icon_set[name])

    def UpdateTooltip(self, action_name : str, label : str):
        """
        Update the label of a command
        """
        action : QAction|None = self._actions.get(action_name)
        if action:
            action.setToolTip(label)

    def UpdateBusyStatus(self):
        """
        Update the toolbar status based on the current state of the project
        """
        datamodel : ProjectDataModel = self.gui.GetDataModel()

        if not datamodel or not datamodel.is_project_initialised:
            self.DisableActions([ "Save Project", "Start Translating", "Start Translating Fast", "Stop Translating", "Undo", "Redo" ])
            self.EnableActions([ "Load Subtitles" ])
            return

        # Enable or disable toolbar commands  depending on whether any translations are ongoing
        command_queue : CommandQueue = self.gui.GetCommandQueue()
        if command_queue.Contains(type_list = [TranslateSceneCommand, StartTranslationCommand]):
            self.DisableActions([ "Load Subtitles", "Save Project", "Start Translating", "Start Translating Fast", "Undo", "Redo"])
            self.EnableActions([ "Stop Translating" ])
            return

        self.DisableActions(["Stop Translating"])

        no_blocking_commands = not command_queue.has_blocking_commands
        self.SetActionsEnabled([ "Load Subtitles", "Save Project", "Start Translating" ], no_blocking_commands)
        self.SetActionsEnabled([ "Start Translating Fast" ], no_blocking_commands and datamodel.allow_multithreaded_translation)
        self.SetActionsEnabled([ "Undo" ], no_blocking_commands and command_queue.can_undo)
        self.SetActionsEnabled([ "Redo" ], no_blocking_commands and command_queue.can_redo)

    def UpdateSaveButton(self):
        """
        Update the save button to indicate whether the project needs saving
        """
        if self._shift_pressed:
            return

        datamodel : ProjectDataModel = self.gui.GetDataModel()
        action : QAction|None = self._actions.get("Save Project")
        if not action:
            return

        if datamodel and datamodel.project and not datamodel.project.needs_writing:
            self.SetActionsEnabled(["Save Project"], False)

    def UpdateTranslateButtons(self):
        """
        Update translate buttons to disable them when project is fully translated, unless shift is pressed
        """
        if self._shift_pressed:
            return

        datamodel : ProjectDataModel = self.gui.GetDataModel()
        if datamodel and datamodel.project and datamodel.project.all_translated:
            self.SetActionsEnabled(["Start Translating", "Start Translating Fast"], False)

    def UpdateTooltips(self):
        """
        Update the labels on the toolbar
        """
        # Update shift-sensitive tooltips for all actions
        for name, action in self._actions.items():
            shortcut = action.shortcut().toString() if action.shortcut() else None
            self._update_action_tooltip(action, name, shortcut)
        
        # Update dynamic tooltips for undo/redo
        command_queue : CommandQueue = self.gui.GetCommandQueue()
        if command_queue.can_undo:
            last_command = command_queue.undo_stack[-1]
            self.UpdateTooltip("Undo", _("Undo {command}").format(command=type(last_command).__name__))
        else:
            self.UpdateTooltip("Undo", _("Nothing to undo"))

        if command_queue.can_redo:
            next_command = command_queue.redo_stack[-1]
            self.UpdateTooltip("Redo", _("Redo {command}").format(command=type(next_command).__name__))
        else:
            self.UpdateTooltip("Redo", _("Nothing to redo"))

    def _icon_file(self, icon_name : str) -> str:
        """
        Get the file path for an icon
        """
        return GetResourcePath("assets", "icons", f"{icon_name}.svg")

    def eventFilter(self, obj, event):
        """
        Global event filter to capture shift key press/release events
        """
        # Always track shift state, but only update UI when main window has focus
        should_update_ui = self.gui.GetMainWindow().isActiveWindow()
        
        if event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Shift:
                if not self._shift_pressed:
                    self._shift_pressed = True
                    if should_update_ui:
                        self.UpdateToolbar()
        elif event.type() == event.Type.KeyRelease:
            if event.key() == Qt.Key.Key_Shift:
                if self._shift_pressed:
                    self._shift_pressed = False
                    if should_update_ui:
                        self.UpdateToolbar()
        elif event.type() == event.Type.WindowActivate:
            # Reset toolbar when main window regains focus (shift state probably changed)
            if obj == self.gui.GetMainWindow():
                self._shift_pressed = False
                self.UpdateToolbar()
        
        return super().eventFilter(obj, event)

def _create_disabled_icon(svg_path : str) -> QIcon:
    """Generate a disabled version of an SVG icon"""
    try:
        with open(svg_path, 'r', encoding='utf-8') as f:
            svg_content = f.read()
        
        # Replace colors for disabled look
        disabled_svg = svg_content.replace('fill="#fff"', 'fill="#D0D0D0"')
        disabled_svg = disabled_svg.replace('fill="white"', 'fill="#D0D0D0"')
        disabled_svg = disabled_svg.replace('stroke="#000"', 'stroke="#808080"')
        disabled_svg = disabled_svg.replace('stroke="black"', 'stroke="#808080"')
        disabled_svg = disabled_svg.replace('fill="black"', 'fill="#606060"')
        
        # Create QIcon from modified SVG
        svg_bytes = QByteArray(disabled_svg.encode('utf-8'))
        svg_renderer = QSvgRenderer(svg_bytes)
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        svg_renderer.render(painter)
        painter.end()
        
        disabled_icon = QIcon()
        disabled_icon.addPixmap(pixmap)
        return disabled_icon
        
    except Exception as e:
        print(f"Failed to create disabled icon for {svg_path}: {e}")
        return QIcon(svg_path)  # Fallback to original
