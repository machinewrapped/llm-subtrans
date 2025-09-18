from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QToolBar, QStyle, QApplication

from GuiSubtrans.ProjectActions import ProjectActions
from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Resources import GetResourcePath

class ProjectToolbar(QToolBar):
    _show_options = True

    def __init__(self, action_handler : ProjectActions, parent=None):
        super().__init__(_("Project Toolbar"), parent)

        self.setOrientation(Qt.Orientation.Vertical)
        self.setMovable(False)

        self.action_handler = action_handler

        self._toggle_options_btn = QAction(self.show_setting_icon, _("Hide/Show Project Options"), self)
        self._toggle_options_btn.triggered.connect(self._toggle_settings)
        self.addAction(self._toggle_options_btn)

    def UpdateUiLanguage(self):
        """Refresh translatable text after language switch."""
        self.setWindowTitle(_("Project Toolbar"))
        self._toggle_options_btn.setText(_("Hide/Show Project Options"))
        # Also refresh icon which depends on state
        self._toggle_options_btn.setIcon(self.show_setting_icon)

    def _toggle_settings(self):
        self.show_settings = not self.show_settings
        self.action_handler.ShowProjectSettings(self.show_settings)

    @property
    def show_settings(self):
        return self._show_options

    @show_settings.setter
    def show_settings(self, value):
        self._show_options = value
        self._toggle_options_btn.setIcon(self.show_setting_icon)

    @property
    def show_setting_icon(self):
        """Return the icon for the toggle settings button."""
        if self.show_settings:
            return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ArrowLeft)
        else:
            return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight)
