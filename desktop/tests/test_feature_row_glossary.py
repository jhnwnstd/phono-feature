"""Glossary-link behaviour of the desktop :class:`FeatureRow`.

A feature with an INLP glossary entry gets an underlined, pointer-cursor
name whose click opens the glossary page in the system browser; a
feature without an entry stays a plain name.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, QPointF, QRect, Qt
from PyQt6.QtGui import QDesktopServices, QMouseEvent
from PyQt6.QtWidgets import QApplication

from phonology_features.gui.widgets.feature_row import FeatureRow

_CORONAL = "https://inlpglossary.ca/coronal/"


def _press_at(x: float, y: float) -> QMouseEvent:
    return QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(x, y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def test_linked_feature_row_is_underlined_and_clickable(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = FeatureRow("Coronal")
    assert row._glossary_url == _CORONAL
    assert row.name_label.font().underline() is True
    assert row.name_label.cursor().shape() == Qt.CursorShape.PointingHandCursor
    # A left click over the name opens the glossary page.
    row.name_label.setGeometry(QRect(0, 0, 180, 28))
    opened: list[str] = []
    monkeypatch.setattr(
        QDesktopServices,
        "openUrl",
        lambda url: bool(opened.append(url.toString())),
    )
    row.mousePressEvent(_press_at(50, 14))
    assert opened == [_CORONAL]


def test_click_outside_the_name_does_not_open(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = FeatureRow("Coronal")
    row.name_label.setGeometry(QRect(0, 0, 180, 28))
    opened: list[str] = []
    monkeypatch.setattr(
        QDesktopServices,
        "openUrl",
        lambda url: bool(opened.append(url.toString())),
    )
    # A point past the name (over the +/- controls strip) is not a link.
    row.mousePressEvent(_press_at(250, 14))
    assert opened == []


def test_unlinked_feature_row_is_plain(qapp: QApplication) -> None:
    row = FeatureRow("Fortis")
    assert row._glossary_url is None
    assert row.name_label.font().underline() is False
    assert row.name_label.cursor().shape() != Qt.CursorShape.PointingHandCursor
