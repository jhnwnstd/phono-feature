"""Qt picker dialog for loading a PHOIBLE 2.0 inventory.

Mirrors the web's PHOIBLE picker UX
(:py:func:`phonology_web.api.phoible_*` endpoints + the
``wirePhoiblePicker`` JS function) so the desktop and web flows
stay aligned:

    Type language -> highlight result -> pick source card -> Load

All non-Qt logic (search, descriptor lookup, segment generation,
inventory composition) lives in the shared
:py:mod:`phonology_shared.editor.phoible_provider` module; this
dialog is the Qt thin shell that wires those calls to widgets.
Per the project's single-source-of-truth approach: a future
PHOIBLE schema change, name-template tweak, or feature mapping
update flows through the shared layer once and both UIs pick it
up automatically.

The dialog never mutates the application's engine itself. On
:py:meth:`accept`, it exposes the chosen :py:class:`Inventory` on
:py:attr:`chosen_inventory`; the caller swaps it into the active
engine and refreshes the UI exactly as it would for any other
file-based load.

Skipped at construction (returns ``None`` from
:py:func:`create_phoible_dialog`) if the PHOIBLE snapshot is not
present in the bundled shared package. The toolbar button stays
disabled in that case so the user never sees a dialog that cannot
do anything.
"""

from __future__ import annotations

from typing import cast

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtGui import QFont, QKeyEvent, QShowEvent
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from phonology_features.gui.style_utils import set_css
from phonology_shared.data.inventory import Inventory
from phonology_shared.editor.inventory_providers import InventoryDescriptor
from phonology_shared.editor.phoible_provider import (
    PhoibleProvider,
    PhoibleSnapshotNotAvailable,
    materialize_phoible_inventory,
)
from phonology_shared.presentation.palette import C

# Type-only role for stashing the inventory id on a source-card
# QListWidgetItem; ``Qt.ItemDataRole.UserRole`` is the canonical
# user-data slot Qt reserves for application use.
_INVENTORY_ID_ROLE = Qt.ItemDataRole.UserRole

# Debounce window between the user's last keystroke and the
# autocomplete query. Matches the web picker's ``SEARCH_DEBOUNCE_MS``
# (180 ms) so both UIs feel identical under typing.
_SEARCH_DEBOUNCE_MS = 180


def create_phoible_dialog(
    parent: QWidget | None = None,
) -> PhoibleDialog | None:
    """Construct a :py:class:`PhoibleDialog` if the PHOIBLE snapshot
    is available; return ``None`` if the bake has not run on this
    checkout.

    The toolbar button calls this once at click time and surfaces
    the ``None`` result as a friendly status-bar message. The
    construction failure is not an error: a developer checkout that
    has never run ``web/scripts/bake_phoible.py`` simply does not
    have PHOIBLE available, and the dialog must not crash.
    """
    try:
        provider = PhoibleProvider()
    except PhoibleSnapshotNotAvailable:
        return None
    return PhoibleDialog(provider, parent)


class PhoibleDialog(QDialog):
    """Picker dialog for loading a PHOIBLE 2.0 inventory.

    Lifecycle:

      1. User types in the search box; results render in the
         autocomplete list with arrow-key navigation.
      2. Enter or click on a language renders the source cards
         for that language and pre-selects the median-sized
         source so the typical user gets a sensible default.
      3. Each source-card pick refreshes the preview pane (segment
         count, feature count, dialect, sample glyphs).
      4. Load materialises the inventory via the shared
         :py:func:`materialize_phoible_inventory` and stores it on
         :py:attr:`chosen_inventory`; the caller picks it up after
         :py:meth:`exec` returns ``Accepted``.
    """

    def __init__(
        self,
        provider: PhoibleProvider,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Load inventory from PHOIBLE")
        self.setMinimumSize(540, 540)
        self.setWindowModality(Qt.WindowModality.WindowModal)

        self._provider = provider
        # Populated by :py:meth:`accept` and read by the caller.
        # ``None`` when the dialog is cancelled or never reached the
        # load step.
        self.chosen_inventory: Inventory | None = None

        # Active inventory id selected in the source-card chooser;
        # ``None`` before the user has picked anything.
        self._selected_inventory_id: str | None = None

        # Search debounce: re-running ``search_languages`` on every
        # keystroke would jitter the result list; 180 ms idle settles
        # the user's input first.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(_SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._run_search)

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        hint = QLabel("Type a language name or ISO 639-3 code to begin.", self)
        hint.setFont(QFont("Noto Sans", 9))
        set_css(hint, f"color: {C['text_dim']};")
        layout.addWidget(hint)

        layout.addWidget(self._build_search_row())
        layout.addWidget(self._build_results_list(), stretch=1)
        layout.addWidget(self._build_source_section(), stretch=1)
        layout.addWidget(self._build_preview_section())
        layout.addWidget(self._build_buttons())

    def _build_search_row(self) -> QWidget:
        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        label = QLabel("Language:", row)
        label.setFont(QFont("Noto Sans", 10, QFont.Weight.DemiBold))
        row_layout.addWidget(label)
        self._search_edit = QLineEdit(row)
        self._search_edit.setPlaceholderText("e.g. Korean, kor")
        self._search_edit.setMinimumHeight(28)
        self._search_edit.textChanged.connect(self._on_search_text_changed)
        self._search_edit.installEventFilter(self)
        row_layout.addWidget(self._search_edit, stretch=1)
        return row

    def _build_results_list(self) -> QWidget:
        wrap = QWidget(self)
        wrap_layout = QVBoxLayout(wrap)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        self._results = QListWidget(wrap)
        self._results.setFont(QFont("Noto Sans", 10))
        self._results.setMinimumHeight(120)
        self._results.itemActivated.connect(self._on_language_activated)
        self._results.itemClicked.connect(self._on_language_activated)
        wrap_layout.addWidget(self._results)
        return wrap

    def _build_source_section(self) -> QWidget:
        wrap = QWidget(self)
        wrap_layout = QVBoxLayout(wrap)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        wrap_layout.setSpacing(4)
        title = QLabel("Inventory source:", wrap)
        title.setFont(QFont("Noto Sans", 10, QFont.Weight.DemiBold))
        wrap_layout.addWidget(title)
        self._sources = QListWidget(wrap)
        self._sources.setFont(QFont("Noto Sans", 10))
        self._sources.setMinimumHeight(140)
        self._sources.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
        )
        self._sources.currentItemChanged.connect(self._on_source_changed)
        wrap_layout.addWidget(self._sources)
        return wrap

    def _build_preview_section(self) -> QWidget:
        wrap = QWidget(self)
        wrap_layout = QVBoxLayout(wrap)
        wrap_layout.setContentsMargins(0, 4, 0, 0)
        wrap_layout.setSpacing(4)
        self._summary = QLabel("", wrap)
        self._summary.setFont(QFont("Noto Sans", 9, QFont.Weight.DemiBold))
        self._summary.setWordWrap(True)
        wrap_layout.addWidget(self._summary)
        self._segments_label = QLabel("", wrap)
        self._segments_label.setFont(QFont("Noto Sans Mono", 10))
        self._segments_label.setWordWrap(True)
        set_css(self._segments_label, f"color: {C['text_dim']};")
        wrap_layout.addWidget(self._segments_label)
        return wrap

    def _build_buttons(self) -> QDialogButtonBox:
        box = QDialogButtonBox(self)
        cancel = box.addButton(QDialogButtonBox.StandardButton.Cancel)
        # ``addButton`` returns ``QPushButton | None`` per the Qt
        # binding stub; in practice both calls always return a
        # widget, but ``cast`` keeps mypy honest without an
        # ``assert`` cluttering the runtime path.
        load_btn = cast(
            QPushButton,
            box.addButton(
                "Load inventory", QDialogButtonBox.ButtonRole.AcceptRole
            ),
        )
        load_btn.setEnabled(False)
        if cancel is not None:
            cancel.clicked.connect(self.reject)
        load_btn.clicked.connect(self._on_load_clicked)
        self._load_btn = load_btn
        return box

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def showEvent(self, event: QShowEvent | None) -> None:  # noqa: D401
        """Land the cursor in the search box on first show so the
        user can start typing immediately."""
        super().showEvent(event)
        self._search_edit.setFocus()

    # ------------------------------------------------------------------
    # Search flow
    # ------------------------------------------------------------------

    def _on_search_text_changed(self, _text: str) -> None:
        self._search_timer.start()

    def _run_search(self) -> None:
        query = self._search_edit.text().strip()
        self._results.clear()
        if not query:
            return
        for name in self._provider.search_languages(query, limit=20):
            QListWidgetItem(name, self._results)
        if self._results.count() > 0:
            self._results.setCurrentRow(0)

    def eventFilter(self, obj: QObject | None, event: QEvent | None) -> bool:
        """Forward Up / Down / Enter from the search field to the
        results list so the user can keyboard-navigate the
        autocomplete without leaving the input. Mirrors the web
        picker's arrow-key handler."""
        if (
            obj is self._search_edit
            and event is not None
            and event.type() == QEvent.Type.KeyPress
        ):
            key_event = cast(QKeyEvent, event)
            key = key_event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                if self._results.count() == 0:
                    return False
                row = self._results.currentRow()
                if key == Qt.Key.Key_Down:
                    row = min(row + 1, self._results.count() - 1)
                else:
                    row = max(row - 1, 0)
                self._results.setCurrentRow(row)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self._results.currentItem()
                if item is not None:
                    self._on_language_activated(item)
                    return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # Source-card flow
    # ------------------------------------------------------------------

    def _on_language_activated(self, item: QListWidgetItem) -> None:
        language = item.text()
        inventories = self._provider.list_inventories(language)
        self._sources.clear()
        self._selected_inventory_id = None
        if not inventories:
            self._summary.setText(
                f"PHOIBLE has no inventories for {language!r}."
            )
            self._segments_label.setText("")
            self._load_btn.setEnabled(False)
            return
        # Default selection: median-segment-count source. Avoids a
        # stray marginal source becoming the user's first impression.
        # Mirrors the web picker's identical default rule.
        sorted_by_size = sorted(inventories, key=lambda d: d.segment_count)
        default_id = sorted_by_size[len(sorted_by_size) // 2].id
        default_row = 0
        for i, descriptor in enumerate(inventories):
            item = QListWidgetItem(
                self._format_source_item(descriptor), self._sources
            )
            item.setData(_INVENTORY_ID_ROLE, descriptor.id)
            if descriptor.id == default_id:
                default_row = i
        self._sources.setCurrentRow(default_row)

    def _format_source_item(self, descriptor: InventoryDescriptor) -> str:
        head = f"{descriptor.source_short}"
        if descriptor.source_description:
            head = f"{head}  -  {descriptor.source_description}"
        line2 = f"{descriptor.segment_count} segments"
        if descriptor.dialect:
            line2 = f"{line2}    {descriptor.dialect}"
        return f"{head}\n{line2}"

    def _on_source_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            self._selected_inventory_id = None
            self._summary.setText("")
            self._segments_label.setText("")
            self._load_btn.setEnabled(False)
            return
        inv_id = cast(str, current.data(_INVENTORY_ID_ROLE))
        self._selected_inventory_id = inv_id
        descriptor = self._provider.descriptor(inv_id)
        if descriptor is None:
            self._load_btn.setEnabled(False)
            return
        # Use the provider directly for the preview rather than
        # going through the materializer (which builds a full
        # Inventory); the preview only needs the segment list +
        # counts and the materialization happens on Load.
        generated = self._provider.generate(inv_id)
        segments = list(generated.segments.keys())
        summary_parts = [
            f"{len(segments)} segments",
            f"{len(generated.features)} features",
        ]
        if descriptor.dialect:
            summary_parts.append(descriptor.dialect)
        self._summary.setText("    ".join(summary_parts))
        sample = segments[:50]
        trail = ""
        if len(segments) > len(sample):
            trail = f"   ... +{len(segments) - len(sample)} more"
        self._segments_label.setText(" ".join(sample) + trail)
        self._load_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def _on_load_clicked(self) -> None:
        if self._selected_inventory_id is None:
            return
        try:
            self.chosen_inventory = materialize_phoible_inventory(
                self._provider, self._selected_inventory_id
            )
        except KeyError:
            # Should not happen since the source list came straight
            # from the provider, but the materializer's contract
            # documents this fail mode and a status-bar message is
            # nicer than an exception trace.
            self.chosen_inventory = None
            return
        self.accept()
