import logging
from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt, QPoint
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QWidget

from GuiSubtrans.Widgets.Widgets import LineItemView

class SubtitleItemDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.render_flags = QWidget.RenderFlag.DrawWindowBackground | QWidget.RenderFlag.DrawChildren

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex|QPersistentModelIndex) -> QWidget:
        return QWidget(parent)  # Return an empty widget to avoid editing

    def paint(self, painter, option, index):
        if not index.isValid() or index.column() != 0:
            return super().paint(painter, option, index)

        widget = index.data(Qt.ItemDataRole.DisplayRole)
        if not isinstance(widget, LineItemView):
            return super().paint(painter, option, index)

        try:
            self.initStyleOption(option, index)

            painter.save()
            painter.translate(option.rect.topLeft())
            widget.setGeometry(option.rect)
            widget.render(painter, QPoint(0,0), renderFlags=self.render_flags)
            painter.restore()
        except Exception as e:
            logging.error(f"Error while painting LineItemView: {e}")

        super().paint(painter, option, index)
