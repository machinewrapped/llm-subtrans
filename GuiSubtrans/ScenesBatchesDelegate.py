from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QStyleOptionViewItem, QStyledItemDelegate, QWidget
from PySide6.QtCore import Qt, QPoint, QModelIndex, QPersistentModelIndex

class ScenesBatchesDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.render_flags = QWidget.RenderFlag.DrawWindowBackground | QWidget.RenderFlag.DrawChildren

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex|QPersistentModelIndex) -> None:
        widget = index.data(role=Qt.ItemDataRole.DisplayRole)

        if widget is None:
            super().paint(painter, option, index)  # Only call the base class if there's no widget
            return

        self.initStyleOption(option, index)

        # Translate painter to the top left of the rectangle provided by option
        painter.save()
        if (hasattr(option, 'rect')):
            rect = getattr(option, 'rect')
            painter.translate(rect.topLeft())
            widget.setGeometry(rect)

        widget.render(painter, QPoint(0, 0), renderFlags=self.render_flags)
        painter.restore()

    def sizeHint(self, option, index):
        widget = index.data(role=Qt.ItemDataRole.DisplayRole)
        if widget:
            self.initStyleOption(option, index)
            widget.setGeometry(option.rect)
            return widget.sizeHint()
        else:
            return super().sizeHint(option, index)
