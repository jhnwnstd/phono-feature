"""InventoryEditor: grid editor for creating or editing inventories."""

import os
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, ClassVar, cast

from phonology_features._logging import get_logger
from phonology_features.gui.controllers.theme import ThemeController
from phonology_features.gui.themed_widgets import (
    statusbar_chrome_qss,
    toolbar_chrome_qss,
)
from phonology_shared.data.inventory import Inventory, ValidationError
from phonology_shared.data.limits import (
    MAX_FEATURES,
    MAX_NAME_LENGTH,
    MAX_SEGMENTS,
)
from phonology_shared.editor.providers import generated_to_grid
from phonology_shared.editor.setup import suggest_filename
from phonology_shared.presentation.mode_logic import (
    REDO_NOTHING_MESSAGE,
    UNDO_NOTHING_MESSAGE,
    added_feature_message,
    added_segment_message,
    inventory_cap_status,
    redid_message,
    removed_feature_message,
    removed_segment_message,
    undid_message,
)

if TYPE_CHECKING:
    # Only used in a string-form type annotation; importing at runtime
    # is pure cost (PyQt6.QtGui.QRegion drags in extra Qt symbols).
    from PyQt6.QtGui import QRegion

from PyQt6.QtCore import QEvent, QModelIndex, QObject, QPoint, Qt
from PyQt6.QtGui import (
    QCloseEvent,
    QFont,
    QKeyEvent,
    QKeySequence,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from phonology_features.gui.controllers.inventory_dir import (
    InventoryDirController,
)
from phonology_features.gui.editor.dialogs import (
    InputDialog,
    ask_question,
    center_on_parent,
    prompt_text,
    show_warning,
)
from phonology_features.gui.editor.edits import (
    _MAX_UNDO_DEPTH,
    _BulkEdit,
    _CellPrev,
    _FeatureEdit,
    _RenameEdit,
    _SegmentEdit,
)
from phonology_features.gui.editor.grid import (
    cycle_value,
    make_cell,
    style_cell,
)
from phonology_features.gui.editor.table import (
    _BulkCycleTable,
    _SelectionFillDelegate,
    _ToggleHeaderView,
)
from phonology_shared.editor.grid import MOVE_KEYS as _SHARED_MOVE_KEYS
from phonology_shared.editor.grid import (
    SELECTION_SHAPE_SINGLE_COLUMN,
    SELECTION_SHAPE_SINGLE_ROW,
)
from phonology_shared.editor.grid import VALUE_KEYS as _SHARED_VALUE_KEYS
from phonology_shared.editor.grid import (
    classify_selection,
    confirm_remove_feature_prompt,
    confirm_remove_segment_prompt,
    grid_to_inventory,
    load_inventory_checked,
    remove_target_for_shape,
    validate_new_feature_label,
    validate_new_segment_label,
)
from phonology_shared.presentation.palette import C

_log = get_logger(__name__)

# Any single undoable action: a cell-value batch or one of the
# structural edits (add / remove segment or feature, rename segment).
_Edit = _BulkEdit | _SegmentEdit | _FeatureEdit | _RenameEdit

# Editor toolbar button height. Matches the main-window toolbar so
# the two surfaces feel like one chrome family at the 1x baseline.
_TOOLBAR_BTN_H = 32


# Translate the JS-native key names in
# :py:data:`phonology_shared.editor.grid.MOVE_KEYS` into ``Qt.Key``
# constants. Arrow keys are named (``ArrowUp``); single-character keys
# (``h``, ``4``) fall through to the ``Key_<X>`` getattr rule. Kept at
# module level so the class-body comprehension that builds
# ``_MOVE_KEYS`` can reference it.
_ARROW_NAME_TO_QT: dict[str, Qt.Key] = {
    "ArrowUp": Qt.Key.Key_Up,
    "ArrowDown": Qt.Key.Key_Down,
    "ArrowLeft": Qt.Key.Key_Left,
    "ArrowRight": Qt.Key.Key_Right,
}


def _move_key_to_qt(name: str) -> Qt.Key:
    """Resolve a logical key name from the shared MOVE_KEYS to a
    Qt key constant. Arrow names use the explicit table; everything
    else (h/j/k/l, 4/5/6/8) uses the ``Key_<X>`` upper-case
    convention.
    """
    if name in _ARROW_NAME_TO_QT:
        return _ARROW_NAME_TO_QT[name]
    return cast(Qt.Key, getattr(Qt.Key, f"Key_{name.upper()}"))


class InventoryEditor(QMainWindow):
    """Grid editor for creating phonological feature inventories."""

    def __init__(
        self,
        parent: QWidget | None = None,
        load_path: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Inventory Editor")
        self.setMinimumSize(800, 500)
        self._segments: list[str] = []
        self._features: list[str] = []
        self._inv_name: str = "Untitled Inventory"
        self._current_path: str | None = None
        self._selected_remove_col: int | None = None
        self._selected_remove_row: int | None = None
        # Bounded invalidation: track the previous selection's region so
        # the next selection change can repaint only (old | new) rather
        # than the entire viewport. Held as a QRegion so the union
        # works for arbitrary shapes (single column, cross, rectangle).
        self._last_selection_region: QRegion | None = None
        # User-click stickies, distinct from the Qt-derived
        # ``_selected_remove_*`` above. Qt auto-selects on header press
        # (before sectionClicked fires on release), so the toggle
        # decision can't read Qt's selection, which would always look
        # "already selected". Mutated only in the header click handlers.
        self._user_clicked_col: int | None = None
        self._user_clicked_row: int | None = None
        # Last applied enabled-state for each rm button. Lets the
        # selection handler short-circuit when nothing changed, so
        # spamming a header click doesn't pay the setStyleSheet polish
        # cost on every event.
        self._rm_seg_enabled_state: bool | None = None
        self._rm_feat_enabled_state: bool | None = None
        # Undo / redo: each entry is one user action. Cell edits are
        # ``_BulkEdit`` batches; structural edits (add / remove
        # segment or feature, rename segment) carry their own records
        # so Ctrl-Z reverses them too. Cleared on table rebuild.
        self._undo_stack: list[_Edit] = []
        self._redo_stack: list[_Edit] = []
        # Provenance for the eventual ``_to_inventory`` save. Set by
        # ``show_setup_dialog`` when the user picks a bootstrap
        # provider (PanPhon, etc.); cleared on ``_load_existing`` so
        # an existing inventory's metadata is not overwritten with
        # this run's provider name.
        self._feature_source: str | None = None
        self._feature_source_version: str | None = None
        # Full metadata carried from a loaded inventory (all but
        # ``name``), merged back on save so stamps the grid cannot edit
        # (PHOIBLE provenance, diphthong ``segment_secondary`` bundles)
        # survive an editor round-trip.
        self._extra_metadata: dict[str, Any] = {}
        self._build_ui()
        # SaveController owns the save state and cross-thread signals.
        # Built after _build_ui because it needs the status bar.
        # _to_inventory is passed as a callback so the controller never
        # has to know about the grid widgets.
        from phonology_features.gui.editor.save_controller import (
            _SaveController,
        )

        self._save_ctrl = _SaveController(
            self, self._status, self._to_inventory
        )
        if parent is not None:
            parent_screen = parent.screen()
            if parent_screen is not None:
                avail = parent_screen.availableGeometry()
                self.resize(
                    min(1000, avail.width() - 80),
                    min(700, avail.height() - 80),
                )
                frame = self.frameGeometry()
                frame.moveCenter(avail.center())
                self.move(frame.topLeft())
        if load_path:
            self._load_existing(load_path)

    def _build_ui(self) -> None:
        self._build_toolbar()
        self._build_central()
        self._build_status_bar()
        # Standard save/open accelerators, active anywhere in the editor
        # window (the table's own event filter owns Ctrl+Z/Y). They mirror
        # the Save / Open toolbar buttons, so no new UI is added.
        QShortcut(QKeySequence.StandardKey.Save, self, self._save)
        QShortcut(QKeySequence.StandardKey.Open, self, self._open_file)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setStyleSheet(toolbar_chrome_qss())
        self.addToolBar(toolbar)
        # Shared with the main toolbar's nav and filled action buttons
        # via ThemeController so the styling lives in one place.
        btn_style = ThemeController.nav_btn_style()
        save_style = ThemeController.filled_btn_style("btn_primary", "0 16px")
        # Destructive action: red fill so it reads as "danger" against
        # the rest of the toolbar's neutral buttons.
        self._delete_style_enabled = ThemeController.filled_btn_style(
            "btn_danger", "0 16px"
        )
        self._btn_style_enabled = btn_style
        # Disabled state: darker and more muted than active buttons so
        # it recedes into the toolbar. See the btn_disabled_* entries
        # in palette.py for the per-theme colour rationale.
        self._btn_style_disabled = f"""
            QPushButton {{
                background: {C["btn_disabled_bg"]};
                color: {C["btn_disabled_text"]};
                border: 1.5px solid {C["btn_disabled_border"]};
                border-radius: 6px;
                padding: 0 12px;
            }}
        """

        def make_btn(
            label: str,
            slot: Callable[[], object],
            *,
            style: str = btn_style,
            tooltip: str = "",
        ) -> QPushButton:
            """Add a Noto Sans 10 toolbar button.

            Height is pinned via ``_TOOLBAR_BTN_H`` so a hi-DPI
            display does not collapse the row. ``tooltip`` sets a hover
            hint (e.g. that a remove needs a whole column/row selected).
            """
            btn = QPushButton(label)
            btn.setFont(QFont("Noto Sans", 10))
            btn.setFixedHeight(_TOOLBAR_BTN_H)
            btn.setStyleSheet(style)
            if tooltip:
                btn.setToolTip(tooltip)
            btn.clicked.connect(slot)
            toolbar.addWidget(btn)
            return btn

        make_btn(
            "New", self.show_setup_dialog, tooltip="Create a new inventory"
        )
        make_btn("Open", self._open_file, tooltip="Open an inventory file")
        make_btn(
            "Save",
            self._save,
            style=save_style,
            tooltip="Save to the current file",
        )
        make_btn("Save As", self._save_as, tooltip="Save to a new file")
        toolbar.addSeparator()
        make_btn(
            "+ Segment",
            self._add_segment,
            tooltip="Add a segment (a new column)",
        )
        make_btn(
            "+ Feature",
            self._add_feature,
            tooltip="Add a feature (a new row)",
        )
        self._rm_seg_btn = make_btn(
            "\u2212 Segment",
            self._remove_segment,
            tooltip="Remove the selected segment "
            "(click a column header to select it)",
        )
        self._rm_feat_btn = make_btn(
            "\u2212 Feature",
            self._remove_feature,
            tooltip="Remove the selected feature "
            "(click a row header to select it)",
        )
        # Initial state: nothing selected => both greyed out. Use the
        # cache-aware setters so the initial assignment also fills the
        # ``_rm_*_enabled_state`` cache.
        self._set_rm_seg_enabled(False)
        self._set_rm_feat_enabled(False)
        toolbar.addSeparator()
        # Two stretches sandwich Delete in the middle of the empty
        # space: away from the edit cluster on the left AND away from
        # the window's close button on the right.
        left_stretch = QWidget()
        left_stretch.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        toolbar.addWidget(left_stretch)
        # Delete is only valid when an existing file is loaded; enabled
        # by _update_title whenever _current_path changes.
        self._delete_btn = make_btn(
            "Delete",
            self._delete_inventory,
            tooltip="Delete the inventory file from disk",
        )
        self._delete_btn.setEnabled(False)
        self._delete_btn.setStyleSheet(self._btn_style_disabled)
        right_stretch = QWidget()
        right_stretch.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        toolbar.addWidget(right_stretch)

    def _build_central(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_meta_strip())
        layout.addWidget(self._build_table())

    def _build_meta_strip(self) -> QWidget:
        """Editable inventory-name field + current-file indicator.

        Sits above the grid so it's clear what you'll be saving and
        where, before any cell edit. Editing the name marks the
        inventory dirty; Save / Save As pick up the new name on write.
        """
        strip = QWidget()
        strip.setStyleSheet(
            f"background: {C['bg']};"
            f" border-bottom: 1px solid {C['border']};"
        )
        lay = QHBoxLayout(strip)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(8)
        name_label = QLabel("Name:")
        name_label.setFont(QFont("Noto Sans", 9, QFont.Weight.Bold))
        name_label.setStyleSheet(f"color: {C['text_dim']};")
        lay.addWidget(name_label)
        self._name_edit = QLineEdit(self._inv_name)
        # UI cap mirrors Inventory.MAX_NAME_LENGTH so the field stops
        # at the limit instead of deferring the error to save.
        self._name_edit.setMaxLength(MAX_NAME_LENGTH)
        self._name_edit.setFont(QFont("Noto Sans", 10))
        self._name_edit.setStyleSheet(f"""
            QLineEdit {{
                background: {C["panel"]};
                color: {C["text"]};
                border: 1px solid {C["border"]};
                border-radius: 4px;
                padding: 2px 8px;
            }}
            QLineEdit:focus {{
                border: 1.5px solid {C["accent"]};
            }}
        """)
        self._name_edit.editingFinished.connect(self._on_name_edited)
        lay.addWidget(self._name_edit, stretch=1)
        self._file_label = QLabel("(unsaved)")
        self._file_label.setFont(QFont("Noto Sans", 9))
        self._file_label.setStyleSheet(
            f"color: {C['text_dim']}; padding: 0 4px;"
        )
        lay.addWidget(self._file_label)
        return strip

    def _install_headers(self) -> None:
        """Install the custom :class:`_ToggleHeaderView` on both axes
        and wire each axis' click and rename signals.

        Shared by :meth:`_build_table` and :meth:`_rebuild_table`:
        ``clear()`` drops our headers back to a plain QHeaderView, so
        the rebuild path must re-install and re-wire them. A fresh
        QHeaderView starts hidden and Qt does not auto-show it on
        ``setHorizontalHeader``; without the explicit ``show()`` the
        label area paints at 0 height and the grid shows no labels (the
        New-Inventory blank-labels bug).
        """
        self._table.setHorizontalHeader(
            _ToggleHeaderView(Qt.Orientation.Horizontal, self._table)
        )
        self._table.setVerticalHeader(
            _ToggleHeaderView(Qt.Orientation.Vertical, self._table)
        )
        h_header = self._table.horizontalHeader()
        v_header = self._table.verticalHeader()
        if h_header is not None:
            h_header.show()
            # _ToggleHeaderView forwards doubleclick -> press, so every
            # user click fires sectionClicked exactly once.
            h_header.sectionClicked.connect(self._on_col_header_clicked)
            self._wire_col_header_rename(h_header)
        if v_header is not None:
            v_header.show()
            # Right-align the feature labels so each hugs the grid row it
            # heads, matching the web editor's row-header pane.
            v_header.setDefaultAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            v_header.sectionClicked.connect(self._on_row_header_clicked)

    def _build_table(self) -> QTableWidget:
        self._table = _BulkCycleTable()
        # Install + wire the custom headers before any other setup
        # (shared with _rebuild_table).
        self._install_headers()
        self._table.set_bulk_cycle_callback(self._cycle_selection_from)
        self._table.setFont(QFont("Noto Sans", 10))
        self._table.setStyleSheet(f"""
            QTableWidget {{
                background: {C["panel"]};
                gridline-color: {C["border"]};
                border: none;
            }}
            QTableWidget::item {{
                padding: 2px 4px;
            }}
            QHeaderView::section {{
                background: {C["bg"]};
                color: {C["text"]};
                border: 1px solid {C["border"]};
                padding: 4px;
                font-weight: bold;
            }}
            """)
        # Selected cells get a light-blue fill + outer outline (delegate).
        self._table.setItemDelegate(_SelectionFillDelegate(self._table))
        # Key-handling event filter only; click-to-select and
        # click-to-cycle live in _BulkCycleTable.mousePressEvent.
        self._table.installEventFilter(self)
        # Single source of truth for rm-button enabled state: fires for
        # every selection change regardless of source. Setters inside
        # short-circuit when nothing changed.
        sel_model = self._table.selectionModel()
        if sel_model is not None:
            sel_model.selectionChanged.connect(self._on_selection_changed)
        # Corner button (top-left of headers) drives select-all by
        # default; intercept so a second click clears the selection.
        corner = self._table.findChild(QAbstractButton)
        if corner is not None:
            try:
                corner.clicked.disconnect()
            except TypeError:
                pass
            corner.clicked.connect(self._on_corner_clicked)
        return self._table

    def _build_status_bar(self) -> None:
        self._status = QStatusBar()
        self._status.setStyleSheet(statusbar_chrome_qss())
        self.setStatusBar(self._status)
        # Live cap counter, pinned to the right so transient
        # showMessage() text never overwrites it. Populated by
        # ``_refresh_cap_counter`` on every grid mutation; hidden
        # until a grid exists.
        self._cap_label = QLabel()
        self._cap_label.setVisible(False)
        self._status.addPermanentWidget(self._cap_label)
        self._status.showMessage(
            "Create a new inventory or open an existing one."
        )

    def _cell_text(self, row: int, col: int) -> str:
        """The grid cell's text, or ``"0"`` for an empty/missing cell.

        Centralizes the QTableWidgetItem-or-default read that every
        grid snapshot performs.
        """
        item = self._table.item(row, col)
        return item.text() if item is not None else "0"

    def _refresh_cap_counter(self) -> None:
        """Recompute the vowel/consonant/total counter from the live
        grid. Cheap at capped sizes, so it runs on every mutation
        rather than tracking deltas. Colours come from the shared
        palette so desktop and web counters read identically."""
        if not self._segments:
            self._cap_label.setVisible(False)
            return
        segments: dict[str, dict[str, str]] = {}
        for c, seg in enumerate(self._segments):
            bundle: dict[str, str] = {}
            for r, feat in enumerate(self._features):
                val = self._cell_text(r, c)
                if val != "0":
                    bundle[feat] = val
            segments[seg] = bundle
        status = inventory_cap_status(segments)
        color = {
            "warn": C["status_warn"],
            "error": C["status_error"],
        }.get(status.severity, C["text_dim"])
        self._cap_label.setStyleSheet(f"color: {color}; padding: 0 8px;")
        self._cap_label.setText(status.text)
        self._cap_label.setVisible(True)

    # Setup dialog
    def show_setup_dialog(self) -> bool:
        """Show the new-inventory setup dialog. Returns True if the user
        committed and a grid was built; False if they cancelled or the
        unsaved-changes check refused.

        The dialog validates its own input (see InputDialog.accept), so on
        a True return the segments/features lists are guaranteed non-empty.
        """
        if not self._check_unsaved():
            return False
        dlg = InputDialog(self)
        center_on_parent(dlg, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        # Dedupe (preserving order). InputDialog.accept already guaranteed
        # both lists are non-empty.
        segments = list(dict.fromkeys(dlg.get_segments()))
        features = list(dict.fromkeys(dlg.get_features()))
        provider = dlg.get_chosen_provider()
        initial_cells: Mapping[str, Mapping[str, str]] | None = None
        status_suffix = ""
        if provider is not None:
            # Provider-driven bootstrap. The provider's feature list is
            # canonical (matches the value-vector shape ``generate``
            # emits), so use it verbatim even if the user edited the
            # textarea; a mismatch would misalign columns and values.
            generated = provider.generate(segments)
            features = list(generated.features)
            # Assemble the grid in the user's segment order via the shared
            # helper (same call the web makes), so the two frontends can't
            # diverge on column order or dedup.
            initial_cells = generated_to_grid(segments, generated)
            self._feature_source = provider.name
            self._feature_source_version = provider.version
            for warning in generated.warnings:
                _log.info("inventory bootstrap: %s", warning)
            if generated.unresolved:
                n_total = len(segments)
                n_unresolved = len(generated.unresolved)
                n_resolved = n_total - n_unresolved
                status_suffix = (
                    f" Generated {n_resolved} of {n_total} via "
                    f"{provider.name}; {n_unresolved} unresolved "
                    "(edit by hand)."
                )
            else:
                status_suffix = f" Generated via {provider.name}."
        else:
            self._feature_source = None
            self._feature_source_version = None
        self._segments = segments
        self._features = features
        self._inv_name = dlg.get_name()
        self._current_path = None
        self._dirty = True
        self._rebuild_table(initial_cells=initial_cells)
        self._update_title()
        self._status.showMessage(
            f"Created grid: {len(segments)} segments "
            f"\u00d7 {len(features)} features. "
            "Click cells to cycle through +/\u2212/0." + status_suffix
        )
        return True

    # Table management
    def _rebuild_table(
        self,
        initial_cells: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        """Build the table: rows=features, cols=segments.

        ``initial_cells`` seeds the grid from a provider-generated
        bundle map. Each cell at ``(feature, segment)`` reads from
        ``initial_cells.get(segment, {}).get(feature, "0")`` so
        missing entries fall through to the existing zero-fill. The
        default ``None`` preserves the original blank-grid behaviour
        for the user-typed-features path.
        """
        # Edits captured against the previous table refer to row/col
        # indices that may no longer match the new table; drop them.
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._table.clear()
        self._table.setRowCount(len(self._features))
        self._table.setColumnCount(len(self._segments))
        # clear() drops our custom headers back to a plain QHeaderView;
        # re-install before labels so the per-click haptic and rename
        # affordance survive a reload.
        self._install_headers()
        self._table.setVerticalHeaderLabels(self._features)
        self._table.setHorizontalHeaderLabels(self._segments)
        # Per-axis font and Fixed section sizing. Fixed, not
        # ResizeToContents: the adaptive mode re-measured every cell on
        # each data change (a 28-cell column cycle took ~1 s), and
        # values are single-char so it buys nothing. Fixed cut a
        # select-all from 60 s+ to 17 ms.
        v_header = self._table.verticalHeader()
        if v_header:
            v_header.setFont(QFont("Noto Sans", 9))
            v_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
            v_header.setDefaultSectionSize(26)
            v_header.setMinimumSectionSize(24)
        h_header = self._table.horizontalHeader()
        if h_header:
            h_header.setFont(QFont("Noto Sans", 11))
            h_header.setDefaultSectionSize(36)
            h_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
            h_header.setMinimumSectionSize(32)
        # clear() can replace the selectionModel too; re-wire it here.
        sel_model = self._table.selectionModel()
        if sel_model is not None:
            try:
                sel_model.selectionChanged.disconnect(
                    self._on_selection_changed
                )
            except TypeError:
                pass
            sel_model.selectionChanged.connect(self._on_selection_changed)
        for r, feat in enumerate(self._features):
            for c, seg in enumerate(self._segments):
                value = "0"
                if initial_cells is not None:
                    bundle = initial_cells.get(seg)
                    if bundle is not None:
                        value = bundle.get(feat, "0")
                self._table.setItem(r, c, make_cell(value))
        self._refresh_cap_counter()

    # Direct-entry shortcuts, derived from the shared
    # :py:data:`VALUE_KEYS` so desktop and web agree on which key sets
    # which value. Translation: the shared dict is char to value, but
    # Qt KeyPress events carry the Qt.Key.Key_<char> constant.
    _VALUE_KEYS: ClassVar[dict[int, str]] = {
        getattr(Qt.Key, f"Key_{char}"): value
        for char, value in _SHARED_VALUE_KEYS.items()
    }
    # Arrow/Vim/numpad navigation, derived from the shared
    # :py:data:`MOVE_KEYS` so desktop and web agree on directions. The
    # name-to-``Qt.Key`` tables live at module level because class-body
    # comprehensions cannot see sibling class attributes.
    _MOVE_KEYS: ClassVar[dict[int, tuple[int, int]]] = {
        _move_key_to_qt(name): step for name, step in _SHARED_MOVE_KEYS.items()
    }
    # ``Shift+Arrow`` extends Qt's native selection, so the handler
    # returns False for it and lets Qt extend. Plain-arrow handling
    # matches Qt's setCurrentCell, so owning it is safe and keeps both
    # frontends on the same Python movement primitive.
    _ARROW_QT_KEYS: ClassVar[frozenset[int]] = frozenset(
        _ARROW_NAME_TO_QT.values()
    )

    def eventFilter(self, obj: QObject | None, event: QEvent | None) -> bool:
        if (
            obj is self._table
            and event is not None
            and event.type() == event.Type.KeyPress
        ):
            if self._handle_table_key(cast(QKeyEvent, event)):
                return True
        return super().eventFilter(obj, event)

    def _handle_table_key(self, event: QKeyEvent) -> bool:
        """Keyboard shortcuts on the table. Returns True if consumed.

        Ctrl+Z / Ctrl+Shift+Z = undo, Ctrl+Y = redo. Scoped to the
        table so the metadata-strip name field's Qt-built-in text-undo
        is left alone when it has focus. Space cycles the current cell
        (multi-cell when there's a selection); 1/2/3/0 set the value;
        h/j/k/l + 4/5/6/8 move the cursor.
        """
        row = self._table.currentRow()
        col = self._table.currentColumn()
        key = event.key()
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_Z:
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    self._redo()
                else:
                    self._undo()
                return True
            if key == Qt.Key.Key_Y:
                self._redo()
                return True
        if row >= 0 and col >= 0:
            if key == Qt.Key.Key_Space:
                cur_item = self._table.item(row, col)
                if cur_item is not None:
                    self._cycle_selection_from(cur_item)
                return True
            value = self._VALUE_KEYS.get(key)
            if value is not None:
                self._apply_value_to_selection(value, row, col)
                return True
        move = self._MOVE_KEYS.get(key)
        if move is not None and self._table.rowCount() > 0:
            # Defer Shift+Arrow to Qt's native selection extend. The
            # shared MOVE_KEYS handler owns only plain navigation, so
            # the web's parity code can mirror it without reimplementing
            # Qt's selection model.
            shift_held = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            if shift_held and key in self._ARROW_QT_KEYS:
                return False
            dr, dc = move
            start_row = row if row >= 0 else 0
            start_col = col if col >= 0 else 0
            target_row = start_row + dr
            target_col = start_col + dc
            rows = self._table.rowCount()
            cols = self._table.columnCount()
            # Arrowing past the top edge selects the current column as
            # if its header had been clicked; past the left edge
            # selects the row. Mirrors the same behavior in the web
            # editor's ``moveFocused``.
            if target_row < 0 and 0 <= target_col < cols:
                self._table.selectColumn(target_col)
                return True
            if target_col < 0 and 0 <= target_row < rows:
                self._table.selectRow(target_row)
                return True
            new_row = max(0, min(target_row, rows - 1))
            new_col = max(0, min(target_col, cols - 1))
            self._table.setCurrentCell(new_row, new_col)
            return True
        return False

    def _set_cell_value(self, row: int, col: int, value: str) -> None:
        """Write ``value`` to the cell and record the change for undo."""
        item = self._table.item(row, col)
        if item is None or item.text() == value:
            return
        old = item.text()
        item.setText(value)
        style_cell(item, value)
        self._commit_edit(_BulkEdit((_CellPrev(row, col, old),), value))

    def _cycle_selection_from(self, anchor_item: QTableWidgetItem) -> None:
        """Cycle every selected cell to the value ``anchor_item`` would
        cycle to. The anchor is whichever cell the user clicked or is
        currently focused on; its current value picks the destination
        for the whole batch so the selection stays uniform.

        Reads the selection via ``selectionModel().selectedIndexes()``
        which is O(selected). ``selectedItems()`` iterates the entire
        model dict (O(rows*cols)) and was a measurable cost on large
        grids.
        """
        new_val = cycle_value(anchor_item.text())
        sel_model = self._table.selectionModel()
        if sel_model is None or not sel_model.hasSelection():
            # Anchor-only path: keyboard-driven cycle on the current
            # cell with no multi-cell selection (e.g. Space in nav mode).
            self._set_cell_value(
                anchor_item.row(), anchor_item.column(), new_val
            )
            return
        self._apply_value_to_indexes(sel_model.selectedIndexes(), new_val)

    def _apply_value_to_selection(
        self, value: str, fallback_row: int, fallback_col: int
    ) -> None:
        """Set ``value`` on every selected cell. Falls back to the cell
        at ``(fallback_row, fallback_col)`` when there is no multi-cell
        selection; typical case where the user has just navigated to a
        single cell with the keyboard."""
        sel_model = self._table.selectionModel()
        if sel_model is not None and sel_model.hasSelection():
            indexes = sel_model.selectedIndexes()
            if len(indexes) > 1:
                self._apply_value_to_indexes(indexes, value)
                return
        self._set_cell_value(fallback_row, fallback_col, value)

    def _apply_value_to_indexes(
        self, indexes: list[QModelIndex], value: str
    ) -> None:
        """Bulk-write ``value`` to every cell in ``indexes``, skipping
        any that already match. Records the whole batch as one
        undoable edit.

        Wraps the writes in ``setUpdatesEnabled(False)`` +
        ``blockSignals(True)`` so Qt suspends paint scheduling and
        view-update signals for the loop; otherwise each ``setText`` /
        ``setForeground`` schedules its own cascade, and the cumulative
        cost dwarfs the actual work.
        """
        prevs: list[_CellPrev] = []
        table = self._table
        table.setUpdatesEnabled(False)
        was_blocking = table.blockSignals(True)
        try:
            for idx in indexes:
                row, col = idx.row(), idx.column()
                item = table.item(row, col)
                if item is None:
                    continue
                old = item.text()
                if old == value:
                    continue
                prevs.append(_CellPrev(row, col, old))
                item.setText(value)
                style_cell(item, value)
        finally:
            table.blockSignals(was_blocking)
            table.setUpdatesEnabled(True)
        if not prevs:
            return
        # One viewport update covers every changed cell instead of N
        # queued data-change paints. The painter clips to dirty
        # regions, so Qt re-paints only the mutated cells.
        viewport = table.viewport()
        if viewport is not None:
            viewport.update()
        self._commit_edit(_BulkEdit(tuple(prevs), value))

    def _commit_edit(self, edit: _BulkEdit) -> None:
        """Push a non-empty edit onto the undo stack and mark dirty.
        Empty batches are ignored so no-ops don't pollute history.

        Does NOT touch the rm-button enabled state: an edit leaves the
        Qt selection unchanged, so the existing state is still correct.
        The old behaviour (calling ``_clear_remove_selection`` here)
        left the column highlighted but greyed the remove button,
        forcing a header re-click.
        """
        if not edit.cells:
            return
        self._push_undo(edit)
        # Cell edits can flip a feature (e.g. syllabic) that
        # reclassifies a segment between vowel and consonant, so the
        # counter must refresh on value changes, not just structural
        # add / remove.
        self._refresh_cap_counter()

    def _push_undo(self, edit: _Edit) -> None:
        """Record any edit on the undo stack, drop redo history, cap
        the depth, and mark dirty. Single entry point so cell and
        structural edits share one lifecycle."""
        self._undo_stack.append(edit)
        # A new edit invalidates any redo history; same convention as
        # most editors (you can't redo into a divergent timeline).
        self._redo_stack.clear()
        if len(self._undo_stack) > _MAX_UNDO_DEPTH:
            self._undo_stack.pop(0)
        self._dirty = True

    def _undo(self) -> None:
        """Reverse the most recent edit and move it to the redo stack."""
        if not self._undo_stack:
            self._status.showMessage(UNDO_NOTHING_MESSAGE)
            return
        edit = self._undo_stack.pop()
        self._apply_edit(edit, revert=True)
        self._redo_stack.append(edit)
        self._dirty = True
        self._status.showMessage(self._edit_status(edit, undo=True))
        self._refresh_cap_counter()

    def _redo(self) -> None:
        """Re-apply the most recently undone edit."""
        if not self._redo_stack:
            self._status.showMessage(REDO_NOTHING_MESSAGE)
            return
        edit = self._redo_stack.pop()
        self._apply_edit(edit, revert=False)
        self._undo_stack.append(edit)
        self._dirty = True
        self._status.showMessage(self._edit_status(edit, undo=False))
        self._refresh_cap_counter()

    def _apply_edit(self, edit: _Edit, *, revert: bool) -> None:
        """Dispatch an undo (``revert=True``) or redo to the right
        replay path. Cell batches restore values in place; structural
        edits insert or remove the column / row, or restore the
        header label, as the inverse of what they originally did."""
        if isinstance(edit, _BulkEdit):
            self._replay_edit(edit, use_old=revert)
            return
        if isinstance(edit, _SegmentEdit):
            # ``added`` XOR ``revert``: present after add-redo and
            # after removal-undo; absent after add-undo and
            # removal-redo.
            if edit.added != revert:
                self._insert_segment_at(edit.index, edit.segment, edit.values)
            else:
                self._remove_segment_at(edit.index)
            # Column count changed: any header selection now points at
            # a shifted / missing column, so drop it.
            self._clear_remove_selection()
            return
        if isinstance(edit, _FeatureEdit):
            if edit.added != revert:
                self._insert_feature_at(edit.index, edit.feature, edit.values)
            else:
                self._remove_feature_at(edit.index)
            self._clear_remove_selection()
            return
        # _RenameEdit
        self._rename_segment_at(edit.index, edit.old if revert else edit.new)

    def _edit_status(self, edit: _Edit, *, undo: bool) -> str:
        """Status-bar line for an undo / redo of ``edit``. Cell
        batches reuse the shared count templates; structural edits
        name the action."""
        if isinstance(edit, _BulkEdit):
            fmt = undid_message if undo else redid_message
            return fmt(len(edit.cells))
        verb = "Undid" if undo else "Redid"
        if isinstance(edit, _SegmentEdit):
            action = "add" if edit.added else "removal"
            return f"{verb} {action} of segment '{edit.segment}'."
        if isinstance(edit, _FeatureEdit):
            action = "add" if edit.added else "removal"
            return f"{verb} {action} of feature '{edit.feature}'."
        return f"{verb} rename of '{edit.old}' to '{edit.new}'."

    def _replay_edit(self, edit: _BulkEdit, *, use_old: bool) -> None:
        """Apply ``edit`` to the grid (``use_old`` for undo, the shared
        ``new`` for redo). Same batching as ``_apply_value_to_indexes``:
        suspend paint and signals during the loop, one viewport.update()
        at the end. ``new`` is hoisted on the redo path; the per-cell
        ``old`` stays in the triple for the undo path."""
        table = self._table
        table.setUpdatesEnabled(False)
        was_blocking = table.blockSignals(True)
        try:
            if use_old:
                for row, col, old in edit.cells:
                    item = table.item(row, col)
                    if item is None:
                        continue
                    item.setText(old)
                    style_cell(item, old)
            else:
                new = edit.new
                for row, col, _ in edit.cells:
                    item = table.item(row, col)
                    if item is None:
                        continue
                    item.setText(new)
                    style_cell(item, new)
        finally:
            table.blockSignals(was_blocking)
            table.setUpdatesEnabled(True)
        viewport = table.viewport()
        if viewport is not None:
            viewport.update()

    # Header selection / remove button state
    def _on_col_header_clicked(self, col: int) -> None:
        """Toggle segment-column highlight; second click clears it.

        Compares against ``_user_clicked_col`` (this handler's own
        sticky) rather than the Qt-derived ``_selected_remove_col``.
        Qt auto-selects on press, so on release the Qt-derived sticky
        already shows ``col`` and every first click would look like a
        toggle-off.
        """
        if self._user_clicked_col == col:
            self._user_clicked_col = None
            self._user_clicked_row = None
            self._table.clearSelection()
        else:
            # First click on this column: Qt has already auto-selected
            # on press, so just record the click for the next toggle.
            self._user_clicked_col = col
            self._user_clicked_row = None
            # Defensive: re-issue selectColumn in case the press path
            # didn't actually set it (e.g. clicked-while-modifier).
            self._table.selectColumn(col)

    def _on_row_header_clicked(self, row: int) -> None:
        """Toggle feature-row highlight; second click clears it."""
        if self._user_clicked_row == row:
            self._user_clicked_row = None
            self._user_clicked_col = None
            self._table.clearSelection()
        else:
            self._user_clicked_row = row
            self._user_clicked_col = None
            self._table.selectRow(row)

    def _on_corner_clicked(self) -> None:
        """Toggle select-all when the table corner is clicked.

        The everything-selected check sums the selection model's range
        sizes instead of ``len(selectedItems())``, which would
        materialise a Python wrapper per cell (O(rows*cols), ~3,900 on
        a Hayes grid), the cost the other interactive paths avoid.
        """
        rows = self._table.rowCount()
        cols = self._table.columnCount()
        total = rows * cols
        sel_model = self._table.selectionModel()
        selected_count = 0
        if sel_model is not None:
            selection = sel_model.selection()
            # Indexed access: the PyQt6 stubs do not expose
            # QItemSelection's iterator protocol.
            for i in range(len(selection)):
                r = selection[i]
                selected_count += (r.bottom() - r.top() + 1) * (
                    r.right() - r.left() + 1
                )
        if total > 0 and selected_count == total:
            self._table.clearSelection()
        else:
            self._table.selectAll()
        # The corner click overrode any per-header selection, so reset
        # the header handlers' stickies. Otherwise a later click on the
        # same header that was active before is misread as a toggle-off,
        # clearing the selection instead of selecting it (and leaving
        # the remove button disabled).
        self._user_clicked_col = None
        self._user_clicked_row = None

    def _clear_remove_selection(self) -> None:
        """Reset which header is currently selected for removal."""
        self._selected_remove_col = None
        self._selected_remove_row = None
        self._set_rm_seg_enabled(False)
        self._set_rm_feat_enabled(False)

    def _set_rm_seg_enabled(self, enabled: bool) -> None:
        """Toggle the − Segment button's enabled state, skipping the
        setStyleSheet polish if nothing actually changed."""
        if self._rm_seg_enabled_state == enabled:
            return
        self._rm_seg_enabled_state = enabled
        self._rm_seg_btn.setEnabled(enabled)
        self._rm_seg_btn.setStyleSheet(
            self._btn_style_enabled if enabled else self._btn_style_disabled
        )

    def _set_rm_feat_enabled(self, enabled: bool) -> None:
        """Toggle the − Feature button's enabled state, skipping the
        setStyleSheet polish if nothing actually changed."""
        if self._rm_feat_enabled_state == enabled:
            return
        self._rm_feat_enabled_state = enabled
        self._rm_feat_btn.setEnabled(enabled)
        self._rm_feat_btn.setStyleSheet(
            self._btn_style_enabled if enabled else self._btn_style_disabled
        )

    def _on_selection_changed(self) -> None:
        """Single source of truth for everything that derives from the
        current Qt selection: sticky vars, rm-button enabled state,
        and the targeted viewport invalidation.

        Uses ``selectedColumns()`` and ``selectedRows()``, which are
        microsecond cost even on select-all (vs walking ~4000 indexes).
        """
        sel_model = self._table.selectionModel()
        if sel_model is None:
            return
        # Invalidate only the union of the previous and current
        # selection regions. A full ``viewport().update()`` repainted
        # every visible cell per toggle (~768 on Hayes, ~38 ms/click);
        # the bounded region repaints only the cells that change
        # selection state. Profile: the delegate paint dominator
        # dropped from 541 ms / 15360 paints to <20 ms / ~250 paints
        # for a row toggle.
        old_region = self._last_selection_region
        new_region = self._table.visualRegionForSelection(
            sel_model.selection()
        )
        invalid = (
            old_region.united(new_region)
            if old_region is not None
            else new_region
        )
        # Inflate by the outline pen width before repainting.
        # ``visualRegionForSelection`` returns cell interiors, but the
        # 2-px outline pen extends one pixel past the cell boundary. If
        # that neighbour isn't in (old | new), the leaked pen pixels
        # survive as ghost outlines after the selection moves (the
        # artifact seen after shift+arrow grows or shrinks a selection).
        # Use boundingRect (QRegion has no inflate), still bounded by
        # the selection size, not the viewport.
        leaked = invalid.boundingRect().adjusted(-2, -2, 2, 2)
        # ``repaint(region)`` is synchronous, bypassing Qt's paint
        # coalescing. update() would merge rapid clicks into one paint
        # at the end, so nothing appears to change between them (the
        # "sticky" / "click didn't register" symptom). With bounded
        # invalidation each repaint is ~3 ms on Hayes, so 300+
        # clicks/sec stay ahead of paint.
        viewport = self._table.viewport()
        if viewport is not None:
            viewport.repaint(leaked)
        self._last_selection_region = new_region
        # Classify via the shared :py:func:`classify_selection` so
        # desktop and web agree on what counts as a single column or
        # row. Walks selectedIndexes once into the (row, col) iterable
        # the classifier expects; microseconds for typical inventories.
        cells = (
            (idx.row(), idx.column()) for idx in sel_model.selectedIndexes()
        )
        shape = classify_selection(
            cells,
            self._table.rowCount(),
            self._table.columnCount(),
        )
        target = remove_target_for_shape(shape)
        if shape.kind == SELECTION_SHAPE_SINGLE_COLUMN:
            self._selected_remove_col = shape.column
            self._selected_remove_row = None
        elif shape.kind == SELECTION_SHAPE_SINGLE_ROW:
            self._selected_remove_row = shape.row
            self._selected_remove_col = None
        else:
            self._selected_remove_col = None
            self._selected_remove_row = None
        self._set_rm_seg_enabled(target == "segment")
        self._set_rm_feat_enabled(target == "feature")

    # Add / remove segments and features
    # Structural-edit primitives. Each mutates the model lists and the
    # QTableWidget in lockstep; the undo machinery and the user-facing
    # handlers all route through these so a change and its inverse
    # touch identical state.
    def _insert_segment_at(
        self, index: int, seg: str, values: tuple[str, ...]
    ) -> None:
        self._segments.insert(index, seg)
        self._table.insertColumn(index)
        self._table.setHorizontalHeaderItem(index, QTableWidgetItem(seg))
        for r, val in enumerate(values):
            self._table.setItem(r, index, make_cell(val))

    def _remove_segment_at(self, index: int) -> None:
        self._table.removeColumn(index)
        self._segments.pop(index)

    def _capture_segment_values(self, col: int) -> tuple[str, ...]:
        """The column's per-feature cell text, for an undoable removal."""
        out: list[str] = []
        for r in range(len(self._features)):
            out.append(self._cell_text(r, col))
        return tuple(out)

    def _insert_feature_at(
        self, index: int, feat: str, values: tuple[str, ...]
    ) -> None:
        self._features.insert(index, feat)
        self._table.insertRow(index)
        self._table.setVerticalHeaderItem(index, QTableWidgetItem(feat))
        for c, val in enumerate(values):
            self._table.setItem(index, c, make_cell(val))

    def _remove_feature_at(self, index: int) -> None:
        self._table.removeRow(index)
        self._features.pop(index)

    def _capture_feature_values(self, row: int) -> tuple[str, ...]:
        """The row's per-segment cell text, for an undoable removal."""
        out: list[str] = []
        for c in range(len(self._segments)):
            out.append(self._cell_text(row, c))
        return tuple(out)

    def _rename_segment_at(self, index: int, name: str) -> None:
        self._segments[index] = name
        self._table.setHorizontalHeaderItem(index, QTableWidgetItem(name))

    def _add_segment(self) -> None:
        """Prompt for a new segment and add a column.

        The trim + dupe-check rule lives in the shared
        :py:func:`validate_new_segment_label`, so the web editor's
        add-segment flow produces identical error wording.
        """
        value = prompt_text(self, "Add Segment", "Segment symbol (IPA):")
        if value is None:
            return
        try:
            seg = validate_new_segment_label(
                value,
                self._segments,
                max_segments=MAX_SEGMENTS,
            )
        except ValueError as e:
            self._status.showMessage(str(e))
            return
        col = len(self._segments)
        values = tuple("0" for _ in self._features)
        self._insert_segment_at(col, seg, values)
        self._push_undo(
            _SegmentEdit(index=col, segment=seg, values=values, added=True)
        )
        self._status.showMessage(added_segment_message(seg))
        self._refresh_cap_counter()
        # Return focus to the table so Ctrl-Z undoes this immediately
        # (the undo shortcut is scoped to the table's event filter).
        self._table.setFocus()

    def _add_feature(self) -> None:
        """Prompt for a new feature and add a row.

        Trim + dupe-check via the shared
        :py:func:`validate_new_feature_label`.
        """
        value = prompt_text(self, "Add Feature", "Feature name:")
        if value is None:
            return
        try:
            feat = validate_new_feature_label(
                value,
                self._features,
                max_features=MAX_FEATURES,
            )
        except ValueError as e:
            self._status.showMessage(str(e))
            return
        row = len(self._features)
        values = tuple("0" for _ in self._segments)
        self._insert_feature_at(row, feat, values)
        self._push_undo(
            _FeatureEdit(index=row, feature=feat, values=values, added=True)
        )
        self._status.showMessage(added_feature_message(feat))
        self._refresh_cap_counter()
        self._table.setFocus()

    def _remove_segment(self) -> None:
        """Remove the header-selected column (segment)."""
        col = self._selected_remove_col
        if col is None or col < 0 or col >= len(self._segments):
            self._status.showMessage(
                "Click a segment column header to choose which to remove."
            )
            return
        seg = self._segments[col]
        reply = ask_question(
            self, "Remove segment", confirm_remove_segment_prompt(seg)
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        values = self._capture_segment_values(col)
        self._remove_segment_at(col)
        self._push_undo(
            _SegmentEdit(index=col, segment=seg, values=values, added=False)
        )
        self._clear_remove_selection()
        self._status.showMessage(removed_segment_message(seg))
        self._refresh_cap_counter()
        # Return focus to the table so Ctrl-Z undoes the deletion
        # immediately; the undo shortcut is scoped to the table's event
        # filter and the toolbar button held focus through the removal.
        self._table.setFocus()

    def _remove_feature(self) -> None:
        """Remove the header-selected row (feature)."""
        row = self._selected_remove_row
        if row is None or row < 0 or row >= len(self._features):
            self._status.showMessage(
                "Click a feature row header to choose which to remove."
            )
            return
        feat = self._features[row]
        reply = ask_question(
            self, "Remove feature", confirm_remove_feature_prompt(feat)
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        values = self._capture_feature_values(row)
        self._remove_feature_at(row)
        self._push_undo(
            _FeatureEdit(index=row, feature=feat, values=values, added=False)
        )
        self._clear_remove_selection()
        self._status.showMessage(removed_feature_message(feat))
        self._refresh_cap_counter()
        self._table.setFocus()

    def _wire_col_header_rename(self, h_header: QHeaderView) -> None:
        """Enable right-click-to-rename on the segment column headers.
        Re-applied on every table rebuild (the header view is
        recreated by ``clear()``)."""
        h_header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        h_header.customContextMenuRequested.connect(
            self._on_col_header_context_menu
        )

    def _on_col_header_context_menu(self, pos: QPoint) -> None:
        """Right-click a segment column header to rename it. Mirrors
        the web editor's right-click-to-rename on a column header."""
        h_header = self._table.horizontalHeader()
        if h_header is None:
            return
        col = h_header.logicalIndexAt(pos)
        if col < 0 or col >= len(self._segments):
            return
        self._rename_segment_dialog(col)

    def _rename_segment_dialog(self, col: int) -> None:
        """Prompt for a new label for the segment at ``col`` and apply
        it as an undoable rename. Empty, unchanged, or duplicate names
        are rejected (the latter with a status note)."""
        old = self._segments[col]
        value = prompt_text(
            self, "Rename Segment", "Segment symbol (IPA):", initial=old
        )
        if value is None:
            return
        proposed = value.strip()
        if proposed == "" or proposed == old:
            return
        if any(
            s == proposed for i, s in enumerate(self._segments) if i != col
        ):
            self._status.showMessage(
                f"Segment '{proposed}' already exists; rename cancelled."
            )
            return
        self._rename_segment_at(col, proposed)
        self._push_undo(_RenameEdit(index=col, old=old, new=proposed))
        self._status.showMessage(f"Renamed segment '{old}' to '{proposed}'.")
        self._refresh_cap_counter()
        # Return focus to the table so Ctrl-Z undoes the rename now.
        self._table.setFocus()

    # Serialization (save / load)
    def _to_inventory(self) -> Inventory:
        """Snapshot the current grid as a validated ``Inventory``.

        Reads cell text from the QTableWidget into a pure 2D list,
        then delegates to :py:func:`grid_to_inventory` for the
        Unicode-minus normalization, the omit-on-zero rule, and the
        :py:meth:`Inventory.from_grid` round-trip. The shared helper
        is the same one the web editor calls, so the on-disk format
        is identical across both frontends.
        """
        assert self._table.columnCount() == len(self._segments)
        assert self._table.rowCount() == len(self._features)
        cells: list[list[str]] = []
        for r in range(len(self._features)):
            row: list[str] = []
            for c in range(len(self._segments)):
                row.append(self._cell_text(r, c))
            cells.append(row)
        # Start from the carried metadata (PHOIBLE stamps,
        # segment_secondary, user keys) and overlay the live provenance
        # fields. The setup-dialog path carries no metadata.
        metadata: dict[str, Any] = dict(self._extra_metadata)
        if self._feature_source:
            metadata["feature_source"] = self._feature_source
            if self._feature_source_version:
                metadata["feature_source_version"] = (
                    self._feature_source_version
                )
        return grid_to_inventory(
            name=self._inv_name,
            features=self._features,
            segments=self._segments,
            cells=cells,
            metadata=metadata or None,
        )

    # ------------------------------------------------------------------
    # Save state forwarders. The SaveController owns the actual
    # state and signals; these properties keep internal callers
    # (and tests) reading ``self._dirty`` / ``self._save_in_flight``
    # / ``self._save_finished`` without churn.
    # ------------------------------------------------------------------
    @property
    def _save_in_flight(self) -> bool:
        return self._save_ctrl.save_in_flight

    @_save_in_flight.setter
    def _save_in_flight(self, value: bool) -> None:
        self._save_ctrl.save_in_flight = value

    @property
    def _dirty(self) -> bool:
        return self._save_ctrl.dirty

    @_dirty.setter
    def _dirty(self, value: bool) -> None:
        if self._save_ctrl.dirty == value:
            return
        self._save_ctrl.dirty = value
        # Surface the change on the file label's unsaved marker as soon
        # as an edit dirties the grid, not only on the next save/load.
        # (The save path clears dirty on the SaveController directly and
        # refreshes via _update_title, so that side stays covered.)
        self._refresh_meta_strip()

    @property
    def _draining_save(self) -> bool:
        return self._save_ctrl.draining_save

    @_draining_save.setter
    def _draining_save(self, value: bool) -> None:
        self._save_ctrl.draining_save = value

    @property
    def _save_finished(self) -> Any:
        """Signal alias for back-compat. External callers do
        ``editor._save_finished.connect(...)``."""
        return self._save_ctrl.save_finished

    # ------------------------------------------------------------------
    # Save method forwarders
    # ------------------------------------------------------------------
    def _write_json(self, path: str) -> None:
        """Delegates to the SaveController. Name kept for tests."""
        self._save_ctrl.request_save(path)

    def _wait_for_save(self, timeout_ms: int = 5000) -> bool:
        return self._save_ctrl.wait_for_save(timeout_ms)

    def _check_unsaved(self) -> bool:
        return self._save_ctrl.check_unsaved()

    def _save(self) -> None:
        if self._draining_save:
            return
        if self._current_path:
            self._write_json(self._current_path)
        else:
            self._save_as()

    def _save_as(self) -> None:
        if self._draining_save:
            return
        inventories_dir = InventoryDirController.get_inventories_dir()
        dlg = QFileDialog(
            self, "Save Inventory", inventories_dir, "JSON Files (*.json)"
        )
        dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        # Default suffix so the dialog appends ``.json`` before its own
        # overwrite confirmation. Otherwise a bare ``foo`` is confirmed
        # against ``foo`` while ``foo.json`` is written, silently
        # overwriting an existing ``foo.json``. The manual append below
        # is a fallback for non-native dialogs that ignore the default.
        dlg.setDefaultSuffix("json")
        # Pre-fill the filename from the inventory name, slugified to
        # match the inventories/ naming convention; the user can still
        # override it.
        dlg.selectFile(suggest_filename(self._inv_name))
        center_on_parent(dlg, self)
        if not dlg.exec():
            return
        path = dlg.selectedFiles()[0] if dlg.selectedFiles() else ""
        if not path:
            return
        if not path.endswith(".json"):
            path += ".json"
        # Drain any in-flight save first so the re-entrancy guard in
        # ``_write_json`` doesn't silently drop this Save-As (Save then
        # immediate Save-As otherwise did nothing).
        if self._save_in_flight:
            self._wait_for_save()
        # ``_write_json`` starts the async write. ``_current_path`` and
        # the title are adopted only once the write is confirmed, in the
        # controller's success branch. Setting them here would leave a
        # phantom backing file (and a falsely "saved" meta strip plus
        # live Delete button) on a validation-abort or failed write.
        self._write_json(path)

    def _delete_inventory(self) -> None:
        """Delete the on-disk file for the currently-loaded inventory.

        The grid contents stay in memory and are marked dirty so the
        user can immediately Save As to a new name if the deletion was
        a refactor rather than a discard. The main window's directory
        watcher picks up the removal and refreshes its dropdown.
        """
        if self._draining_save:
            return
        path = self._current_path
        if not path:
            return
        fname = os.path.basename(path)
        reply = ask_question(
            self,
            "Delete inventory",
            f"Permanently delete '{fname}' from disk?\n\n"
            "The current grid stays open; Save As to keep a copy.",
            buttons=(
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.Cancel
            ),
            default=QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            os.remove(path)
        except OSError as e:
            show_warning(
                self, "Delete failed", f"Could not delete '{fname}':\n{e}"
            )
            return
        self._current_path = None
        # In-memory grid is now unsaved (no file backs it).
        self._dirty = True
        self._update_title()
        self._status.showMessage(
            f"Deleted '{fname}'. The grid is unsaved; Save As to keep it."
        )

    def _open_file(self) -> None:
        if self._draining_save:
            return
        if not self._check_unsaved():
            return
        inventories_dir = InventoryDirController.get_inventories_dir()
        dlg = QFileDialog(
            self, "Open Inventory", inventories_dir, "JSON Files (*.json)"
        )
        dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
        dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
        center_on_parent(dlg, self)
        if not dlg.exec():
            return
        path = dlg.selectedFiles()[0] if dlg.selectedFiles() else ""
        if path:
            self._load_existing(path)

    def _load_existing(self, path: str) -> None:
        """Load an existing JSON inventory into the grid for editing.

        Routes through ``Inventory.load`` so the editor enforces the
        same contract as the engine: invalid files refuse to load with
        a human-readable error rather than producing a partially-
        normalized grid that gets silently rewritten on save.
        """
        try:
            inventory = load_inventory_checked(path)
        except ValidationError as e:
            show_warning(
                self,
                "Cannot load inventory",
                "This file does not satisfy the inventory contract:\n\n"
                + "\n".join(f"• {issue}" for issue in e.issues),
            )
            return
        self.load_inventory(inventory, path=path)

    def load_inventory(
        self, inventory: Inventory, path: str | None = None
    ) -> None:
        """Seed the grid from an already-validated ``Inventory``.

        ``path`` is the backing file for a disk load, ``None`` for
        in-memory inventories (a PHOIBLE picker result, a
        renamed-but-unsaved one), in which case Save routes through
        Save As. Public so MainWindow can hand the editor the active
        in-memory inventory: a PHOIBLE load has no file path, and the
        editor used to fall back to the setup dialog, which made "load
        from PHOIBLE, edit, then save locally" impossible.
        """
        self._inv_name = inventory.name
        self._features = list(inventory.features)
        self._segments = list(inventory.segments.keys())
        self._current_path = path
        # Preserve any feature-source provenance on the loaded
        # inventory; clearing here would erase the original PanPhon
        # (or future-provider) stamp on the next save. Read both keys
        # defensively since an older release may have written them.
        loaded_source = inventory.metadata.get("feature_source")
        loaded_version = inventory.metadata.get("feature_source_version")
        self._feature_source = (
            str(loaded_source) if isinstance(loaded_source, str) else None
        )
        self._feature_source_version = (
            str(loaded_version) if isinstance(loaded_version, str) else None
        )
        # Carry the full metadata (all but ``name``, which the grid's
        # name field owns) so the next save round-trips it. Keeping
        # only ``feature_source`` used to drop the PHOIBLE stamps and
        # the ``segment_secondary`` diphthong bundles, so editing a
        # PHOIBLE inventory erased its diphthong arrows on save.
        self._extra_metadata = {
            k: v for k, v in inventory.metadata.items() if k != "name"
        }
        # Seed the grid from the parsed bundle directly. The old path
        # built an all-zero grid and then replaced every cell, doubling
        # the ``make_cell`` work (3920 cells on Hayes) and dominating
        # every editor open. Reuse ``_rebuild_table``'s ``initial_cells``
        # seed (already used by the provider path) for a single pass.
        self._rebuild_table(initial_cells=inventory.segments)
        self._dirty = False
        self._update_title()
        self._status.showMessage(
            f"{len(self._segments)} segments \u00d7 "
            f"{len(self._features)} features."
        )

    # Unsaved changes guard
    def closeEvent(self, event: QCloseEvent | None) -> None:
        if event is None:
            return
        if not self._check_unsaved():
            event.ignore()
            return
        # Wait for any background save before Qt destroys the window.
        # A worker emitting ``_save_finished`` after the QObject is
        # gone makes PyQt raise "wrapped C/C++ object has been deleted"
        # on the worker thread. Harmless but noisy, and a clean wait is
        # cheap (a healthy-disk atomic write is sub-ms).
        self._wait_for_save()
        event.accept()

    def _update_title(self) -> None:
        # Window title stays plain; the inventory name and filename
        # already appear in the meta strip below the toolbar, so
        # repeating them in the title bar is noise.
        path = self._current_path
        has_file = bool(path)
        self.setWindowTitle("Inventory Editor")
        # Delete only makes sense when there's an on-disk file backing
        # the current grid; toggle the visual + interactive state.
        self._delete_btn.setEnabled(has_file)
        self._delete_btn.setStyleSheet(
            self._delete_style_enabled
            if has_file
            else self._btn_style_disabled
        )
        self._refresh_meta_strip()

    def _refresh_meta_strip(self) -> None:
        """Sync the name field and file-indicator label with the current
        ``_inv_name`` / ``_current_path``, marking unsaved edits. Used
        after every load, save, or programmatic rename, and on every
        dirty change (via the ``_dirty`` setter), so the visible UI
        matches the data."""
        if self._name_edit.text() != self._inv_name:
            self._name_edit.setText(self._inv_name)
        if self._current_path:
            base = os.path.basename(self._current_path)
            # Trailing bullet marks unsaved edits to the loaded file; the
            # no-file "(unsaved)" state already says as much on its own.
            self._file_label.setText(f"{base} •" if self._dirty else base)
        else:
            self._file_label.setText("(unsaved)")

    def _on_name_edited(self) -> None:
        """Commit the name field's text to ``_inv_name`` once the user
        finishes editing (focus lost or Enter). Marks dirty if the name
        actually changed; refreshes the title bar."""
        new_name = self._name_edit.text().strip() or "Untitled Inventory"
        if new_name == self._inv_name:
            return
        self._inv_name = new_name
        self._dirty = True
        self._update_title()
