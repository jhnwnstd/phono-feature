"""Tests for the InventoryBuilder setup dialog and SegmentTextEdit.

Covers the recently-fixed UX bugs:

  1. Tab on an empty segment box fills in a quick-start segment list
     (and Tab on a populated box doesn't clobber the user's content).
  2. The dialog validates inputs BEFORE dismissing; empty segments
     or empty features no longer close the dialog and then surface
     a warning over an already-gone editor.
  3. The unsaved-changes / cancel paths return False from
     _show_setup_dialog so callers can clean up (e.g. _open_builder
     in MainWindow uses this to avoid flashing an empty builder).
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QDialog, QMessageBox

from phonology_features.gui.builder.dialogs import (
    FeatureTextEdit,
    InputDialog,
    SegmentTextEdit,
)


# ---------------------------------------------------------------------------
# SegmentTextEdit: Tab autofill behavior
# ---------------------------------------------------------------------------
@pytest.fixture
def seg_edit(qapp):
    return SegmentTextEdit()


def _tab(widget) -> None:
    """Dispatch a Tab key press through the widget's event() override.

    SegmentTextEdit catches the Tab in event() (so it can run BEFORE
    Qt's tabChangesFocus routing); calling keyPressEvent directly
    would bypass that branch.
    """
    from PyQt6.QtWidgets import QApplication

    event = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier
    )
    QApplication.sendEvent(widget, event)


def test_tab_on_empty_fills_default(seg_edit):
    assert seg_edit.toPlainText() == ""
    _tab(seg_edit)
    assert seg_edit.toPlainText() == SegmentTextEdit.DEFAULT_FILL


def test_tab_on_whitespace_only_still_fills(seg_edit):
    seg_edit.setPlainText("   \n  \t\n")
    _tab(seg_edit)
    assert seg_edit.toPlainText() == SegmentTextEdit.DEFAULT_FILL


def test_tab_on_existing_content_leaves_it_alone(seg_edit):
    seg_edit.setPlainText("m n \u014b")
    _tab(seg_edit)
    assert seg_edit.toPlainText() == "m n \u014b"


def test_tab_changes_focus_when_content_is_present(seg_edit):
    # The widget configures tabChangesFocus so navigation feels native;
    # the empty-fill behavior is layered on top of that.
    assert seg_edit.tabChangesFocus()


def test_tab_on_empty_fills_but_keeps_focus(qapp):
    """Tab on an empty editor should autofill and KEEP focus in the
    editor; the user shouldn't have a single Tab press both fill the
    seed text and jump to the next widget. A second Tab (now non-empty)
    advances focus."""
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

    container = QWidget()
    layout = QVBoxLayout(container)
    seg = SegmentTextEdit()
    sibling = QLineEdit()
    layout.addWidget(seg)
    layout.addWidget(sibling)
    container.show()
    seg.setFocus()
    qapp.processEvents()
    assert seg.hasFocus()
    # First Tab on empty; fills, keeps focus.
    QTest.keyClick(seg, Qt.Key.Key_Tab)  # type: ignore[call-overload]
    qapp.processEvents()
    assert seg.toPlainText() == SegmentTextEdit.DEFAULT_FILL
    assert seg.hasFocus(), (
        "Tab on empty must NOT advance focus; it only fills. "
        "Pressing Tab again advances normally."
    )
    # Second Tab; now non-empty, should advance focus normally.
    QTest.keyClick(seg, Qt.Key.Key_Tab)  # type: ignore[call-overload]
    qapp.processEvents()
    assert (
        sibling.hasFocus()
    ), "Tab on a filled editor should advance focus to the next widget."
    container.deleteLater()


def test_tab_on_filled_just_moves_focus(qapp):
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

    container = QWidget()
    layout = QVBoxLayout(container)
    seg = SegmentTextEdit()
    seg.setPlainText("m n \u014b")
    sibling = QLineEdit()
    layout.addWidget(seg)
    layout.addWidget(sibling)
    container.show()
    seg.setFocus()
    qapp.processEvents()
    QTest.keyClick(seg, Qt.Key.Key_Tab)  # type: ignore[call-overload]
    qapp.processEvents()
    assert seg.toPlainText() == "m n \u014b"
    assert sibling.hasFocus()
    container.deleteLater()


# ---------------------------------------------------------------------------
# FeatureTextEdit shares the same Tab-autofill behavior with a different fill
# ---------------------------------------------------------------------------
@pytest.fixture
def feat_edit(qapp):
    return FeatureTextEdit()


def test_feature_tab_on_empty_fills_two_major_class_seeds(feat_edit):
    assert feat_edit.toPlainText() == ""
    _tab(feat_edit)
    # Tab seeds only the two major-class features; the user fills in the
    # rest. The full Default (33) preset is reachable via the dropdown.
    # Compare against ``entries()`` since the seed format (space- vs
    # newline-separated) is an implementation detail.
    assert feat_edit.entries() == ["Syllabic", "Consonantal"]


def test_feature_tab_on_existing_content_leaves_it_alone(feat_edit):
    feat_edit.setPlainText("Voice\nNasal")
    _tab(feat_edit)
    assert feat_edit.toPlainText() == "Voice\nNasal"


def test_feature_text_edit_changes_focus_on_tab(feat_edit):
    assert feat_edit.tabChangesFocus()


# ---------------------------------------------------------------------------
# InputDialog wires up FeatureTextEdit (so the feat box gets autofill too)
# ---------------------------------------------------------------------------
def test_dialog_feat_edit_is_feature_text_edit(dialog):
    assert isinstance(dialog.feat_edit, FeatureTextEdit)


def test_dialog_seg_edit_is_segment_text_edit(dialog):
    assert isinstance(dialog.seg_edit, SegmentTextEdit)


# ---------------------------------------------------------------------------
# InputDialog: accept() validates before dismissing
# ---------------------------------------------------------------------------
@pytest.fixture
def dialog(qapp):
    dlg = InputDialog()
    yield dlg
    dlg.deleteLater()


def test_accept_with_empty_segments_does_not_dismiss(dialog, mocker):
    """Calling accept() with empty segments should warn and keep the
    dialog open. Previously this validation ran AFTER the dialog had
    already closed, so the warning surfaced over a dismissed editor."""
    warn = mocker.patch.object(QMessageBox, "warning")
    # Default state: seg edit is empty; features auto-fill from preset.
    assert dialog.get_segments() == []
    assert dialog.get_features()  # preset filled it
    dialog.accept()
    warn.assert_called_once()
    args = warn.call_args.args
    assert args[1] == "No segments found"
    # Dialog must remain in its pre-accept state; Accepted is QDialog.DialogCode.Accepted == 1
    assert dialog.result() != QDialog.DialogCode.Accepted


def test_accept_with_empty_features_does_not_dismiss(dialog, mocker):
    warn = mocker.patch.object(QMessageBox, "warning")
    dialog.seg_edit.setPlainText("p b t")
    dialog.feat_edit.clear()
    assert dialog.get_segments() == ["p", "b", "t"]
    assert dialog.get_features() == []
    dialog.accept()
    warn.assert_called_once()
    assert warn.call_args.args[1] == "No features found"
    assert dialog.result() != QDialog.DialogCode.Accepted


def test_accept_with_valid_inputs_dismisses(dialog, mocker):
    """With both fields populated, accept should call super().accept()
    and the dialog enters the Accepted state."""
    warn = mocker.patch.object(QMessageBox, "warning")
    dialog.seg_edit.setPlainText("p b t")
    # feat_edit was preset-filled in __init__; leave it.
    assert dialog.get_features()
    dialog.accept()
    warn.assert_not_called()
    assert dialog.result() == QDialog.DialogCode.Accepted


# ---------------------------------------------------------------------------
# Delimiter inference: any consistently-delimited paste should parse
# ---------------------------------------------------------------------------
def test_infer_split_whitespace_fallback():
    """No explicit delimiter -> whitespace fallback. Covers the
    legacy "p b t d" segment input shape."""
    from phonology_features.gui.inventory_setup import (
        infer_split as _infer_split,
    )

    assert _infer_split("p b t d") == ["p", "b", "t", "d"]


def test_infer_split_newline_separated():
    from phonology_features.gui.inventory_setup import (
        infer_split as _infer_split,
    )

    assert _infer_split("Syllabic\nConsonantal\nVoice\n") == [
        "Syllabic",
        "Consonantal",
        "Voice",
    ]


def test_infer_split_comma_separated_with_internal_spaces():
    """Explicit delimiter present -> only split on it, NOT on
    whitespace. Lets multi-word feature names like "Long Vowel"
    survive a paste."""
    from phonology_features.gui.inventory_setup import (
        infer_split as _infer_split,
    )

    assert _infer_split("Long Vowel, Short Vowel, Schwa") == [
        "Long Vowel",
        "Short Vowel",
        "Schwa",
    ]


def test_infer_split_semicolon_pipe_tab_each_work():
    from phonology_features.gui.inventory_setup import (
        infer_split as _infer_split,
    )

    assert _infer_split("a; b; c") == ["a", "b", "c"]
    assert _infer_split("a|b|c") == ["a", "b", "c"]
    assert _infer_split("a\tb\tc") == ["a", "b", "c"]


def test_infer_split_mixed_explicit_delimiters():
    """Multiple explicit delimiters in one paste (commas + newlines,
    as you'd get from a column accidentally pasted with both row and
    cell separators) split on all of them."""
    from phonology_features.gui.inventory_setup import (
        infer_split as _infer_split,
    )

    assert _infer_split("p, b, t\nd, e, f") == ["p", "b", "t", "d", "e", "f"]


def test_infer_split_empty_returns_empty():
    from phonology_features.gui.inventory_setup import (
        infer_split as _infer_split,
    )

    assert _infer_split("") == []
    assert _infer_split("   \n\t  ") == []


def test_infer_split_single_item_no_delimiter():
    """A single token with no delimiter at all is preserved as a
    one-item list. accept()'s "no items" guard fires only on truly
    empty input, not on legitimate single-segment inventories."""
    from phonology_features.gui.inventory_setup import (
        infer_split as _infer_split,
    )

    assert _infer_split("Voice") == ["Voice"]


def test_segment_and_feature_editors_share_inference(qapp):
    """The unified delimiter inference means a comma-separated
    paste works in BOTH the segments box and the features box.
    Pre-refactor the segments box used whitespace-split and the
    features box used newline-split, so neither accepted the
    other's natural shape."""
    from phonology_features.gui.builder.dialogs import (
        FeatureTextEdit,
        SegmentTextEdit,
    )

    seg = SegmentTextEdit()
    seg.setPlainText("p, b, t, d")
    assert seg.entries() == ["p", "b", "t", "d"]

    feat = FeatureTextEdit()
    feat.setPlainText("Voice, Nasal, Continuant")
    assert feat.entries() == ["Voice", "Nasal", "Continuant"]
