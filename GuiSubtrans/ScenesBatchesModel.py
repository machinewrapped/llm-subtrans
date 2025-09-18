from PySide6.QtCore import Qt, QAbstractItemModel, QSortFilterProxyModel, QModelIndex, QPersistentModelIndex
from PySide6.QtGui import QStandardItem

from GuiSubtrans.ViewModel.ViewModel import ProjectViewModel
from GuiSubtrans.ViewModel.BatchItem import BatchItem
from GuiSubtrans.ViewModel.ViewModelItem import ViewModelItem
from GuiSubtrans.Widgets.Widgets import TreeViewItemWidget

class ScenesBatchesModel(QSortFilterProxyModel):
    def __init__(self, viewmodel : ProjectViewModel|None = None, parent = None):
        super().__init__(parent)
        if viewmodel:
            self.setSourceModel(viewmodel)

    def filterAcceptsRow(self, source_row : int, source_parent : QModelIndex|QPersistentModelIndex) -> bool:
        if not source_parent.isValid():
            return True

        viewmodel : QAbstractItemModel = self.sourceModel()
        if not viewmodel or not isinstance(viewmodel, ProjectViewModel):
            return False
        
        item = viewmodel.itemFromIndex(source_parent)

        if not item or isinstance(item, BatchItem):
            return False

        return True

    def data(self, index, role : int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        source_index = self.mapToSource(index)
        viewmodel : QAbstractItemModel = self.sourceModel()
        if not viewmodel or not isinstance(viewmodel, ProjectViewModel):
            return False

        item : QStandardItem = viewmodel.itemFromIndex(source_index)
        if not isinstance(item, ViewModelItem):
            return None

        if role == Qt.ItemDataRole.UserRole:
            return item

        if role == Qt.ItemDataRole.DisplayRole:
            return TreeViewItemWidget(item.GetContent())
        
        if role == Qt.ItemDataRole.SizeHintRole:
            return TreeViewItemWidget(item.GetContent()).sizeHint()

        return None
