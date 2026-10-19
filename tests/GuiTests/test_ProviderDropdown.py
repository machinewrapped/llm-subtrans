"""Verify the provider selector groups providers by kind under headings that cannot be selected."""
from tests.GuiTestSupport import ConfigureOffscreenPlatform

ConfigureOffscreenPlatform()

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QApplication

from GuiSubtrans.GuiHelpers import GetProviderDropdownValues
from GuiSubtrans.Widgets.OptionsWidgets import DropdownHeader, DropdownOptionWidget
from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.TranslationProvider import ProviderKind, TranslationProvider


class _DropdownDirectProvider(TranslationProvider):
    name = "Dropdown Direct Provider"

class _DropdownGatewayProvider(TranslationProvider):
    name = "Dropdown Gateway Provider"
    kind = ProviderKind.Gateway

class _DropdownCustomProvider(TranslationProvider):
    name = "Dropdown Custom Provider"
    kind = ProviderKind.Custom


class TestProviderDropdownValues(LoggedTestCase):
    """Provider names are grouped by kind."""

    def test_groups_by_kind_in_fixed_order(self) -> None:
        names = [_DropdownCustomProvider.name, _DropdownGatewayProvider.name, _DropdownDirectProvider.name]
        values = GetProviderDropdownValues(names)

        providers = [value for value in values if not isinstance(value, DropdownHeader)]
        header_count = sum(1 for value in values if isinstance(value, DropdownHeader))

        self.assertLoggedEqual("providers ordered by kind",
            [_DropdownDirectProvider.name, _DropdownGatewayProvider.name, _DropdownCustomProvider.name], providers)
        self.assertLoggedEqual("one heading per kind", 3, header_count)
        self.assertLoggedIsInstance("list starts with a heading", values[0], DropdownHeader)

    def test_single_kind_has_no_headings(self) -> None:
        names = [_DropdownGatewayProvider.name]
        self.assertLoggedEqual("names unchanged", names, GetProviderDropdownValues(names))


class TestDropdownHeaders(LoggedTestCase):
    """Headings are shown but never become the value."""

    application : QApplication

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        existing = QApplication.instance()
        cls.application = existing if isinstance(existing, QApplication) else QApplication([])

    def test_headers_are_not_selectable(self) -> None:
        widget = DropdownOptionWidget('provider', [DropdownHeader("Group A"), 'a', DropdownHeader("Group B"), 'b'], 'b')

        model = widget.combo_box.model()
        assert isinstance(model, QStandardItemModel)
        header_flags = model.item(0).flags()

        self.assertLoggedEqual("selected value", 'b', widget.GetValue())
        self.assertLoggedEqual("values exclude headings", ['a', 'b'], widget.values)
        self.assertLoggedFalse("heading not selectable", bool(header_flags & Qt.ItemFlag.ItemIsSelectable))

    def test_unknown_selection_falls_back_to_first_value(self) -> None:
        widget = DropdownOptionWidget('provider', [DropdownHeader("Group A"), 'a', 'b'], 'missing')

        self.assertLoggedEqual("first selectable value", 'a', widget.GetValue())
