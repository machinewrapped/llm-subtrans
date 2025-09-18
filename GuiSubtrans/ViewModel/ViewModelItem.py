from typing import Any

from PySide6.QtGui import QStandardItem

class ViewModelItem(QStandardItem):
    def GetContent(self) -> dict[str, Any]:
        return {
            'heading': "Item Heading",
            'subheading': "Optional Subheading",
            'body': "Body Content",
            'properties': {}
        }