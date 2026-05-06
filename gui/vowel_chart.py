"""
gui/vowel_chart.py

IPA-style vowel trapezoid chart widget.

Maps vowel segments onto a height x backness x rounding grid using
normalised phonological features. Placement is inventory-sensitive.
A VowelProfile is computed once per inventory to determine which
features are active, so fallback logic only fires when the inventory
actually lacks the direct feature.

Each placement carries a confidence level and a human-readable reason
string, surfaced as tooltips on the buttons.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from gui.palette import C

VOWEL_LABEL_W = 72
_VOWEL_HEIGHT: list = [
    ("Close", "+", "-", "+"),
    ("Near-close", "+", "-", "-"),
    ("Close-mid", "-", "-", "+"),
    ("Open-mid", "-", "-", "-"),
    ("Near-open", "-", "+", "-"),
    ("Open", "-", "+", None),
]
_ROW_LABELS = [label for label, *_ in _VOWEL_HEIGHT]


@dataclass(frozen=True)
class VowelProfile:
    """Which vowel-relevant features are actively used in this inventory."""

    has_front: bool
    has_back: bool
    has_round: bool
    has_labial: bool
    has_high: bool
    has_low: bool
    has_atr: bool
    has_tense: bool
    has_coronal: bool
    has_anterior: bool

    @property
    def use_coronal_front_fallback(self) -> bool:
        """Use CORONAL as a proxy for frontness only when Front is absent."""
        has_coronal_feature = self.has_coronal
        lacks_front_feature = not self.has_front
        return has_coronal_feature and lacks_front_feature

    @property
    def has_height_sub_distinction(self) -> bool:
        """True if the inventory uses ATR or Tense to split height tiers."""
        return self.has_atr or self.has_tense

    @property
    def use_labial_round_fallback(self) -> bool:
        """Use LABIAL as a rounding proxy only when Round is absent."""
        has_labial_feature = self.has_labial
        lacks_round_feature = not self.has_round
        return has_labial_feature and lacks_round_feature


def _detect_vowel_profile(segs: list, norm_feats: dict) -> VowelProfile:
    """Scan the vowel segments to determine which features are in play."""
    active: set[str] = set()
    for seg in segs:
        seg_features = norm_feats.get(seg, {})
        for feat, val in seg_features.items():
            feature_is_active = val != "0"
            if feature_is_active:
                active.add(feat)
    return VowelProfile(
        has_front="front" in active,
        has_back="back" in active,
        has_round="round" in active,
        has_labial="labial" in active,
        has_high="high" in active,
        has_low="low" in active,
        has_atr="atr" in active,
        has_tense="tense" in active,
        has_coronal="coronal" in active,
        has_anterior="anterior" in active,
    )


@dataclass(frozen=True)
class VowelPlacement:
    row: int
    col: int
    confidence: str
    reason: str


def _fv(feats: dict, key: str) -> str:
    """Feature value, defaulting to '0'."""
    return feats.get(key, "0")


def _nonzero(val: str | None) -> str | None:
    """Return val only if it carries real feature information."""
    has_value = bool(val)
    is_unspecified = val == "0"
    if has_value and not is_unspecified:
        return val
    return None


def _infer_height(feats: dict, profile: VowelProfile) -> tuple[int, str, str]:
    """Return row, confidence, and reason."""
    hi = _fv(feats, "high")
    lo = _fv(feats, "low")
    tense_value = _nonzero(feats.get("tense"))
    atr_value = _nonzero(feats.get("atr"))
    atr_tn = tense_value or atr_value
    is_high_vowel = hi == "+" and lo == "-"
    is_low_vowel = hi == "-" and lo == "+"
    is_mid_vowel = hi == "-" and lo == "-"
    if is_high_vowel:
        is_near_close = profile.has_height_sub_distinction and atr_tn == "-"
        if is_near_close:
            return 1, "medium", "Near-close: [+high, -low, -tense/ATR]"
        if atr_tn == "+":
            return 0, "high", "Close: [+high, -low, +tense/ATR]"
        return 0, "high", "Close: [+high, -low]"
    if is_low_vowel:
        is_near_open = profile.has_height_sub_distinction and atr_tn == "-"
        if is_near_open:
            return 4, "medium", "Near-open: [-high, +low, -tense/ATR]"
        return 5, "high", "Open: [-high, +low]"
    if is_mid_vowel:
        if atr_tn == "+":
            return 2, "medium", "Close-mid: [-high, -low, +tense/ATR]"
        if atr_tn == "-":
            return 3, "medium", "Open-mid: [-high, -low, -tense/ATR]"
        return 3, "low", "Open-mid (default): [-high, -low], no tense/ATR"
    return 3, "low", "Open-mid (default): underspecified height"


def _infer_backness(
    feats: dict,
    profile: VowelProfile,
) -> tuple[str, str, str]:
    """Return place, confidence, and reason."""
    fr = _nonzero(feats.get("front"))
    bk = _nonzero(feats.get("back"))
    has_positive_front = fr == "+"
    has_positive_back = bk == "+"
    if has_positive_front and not has_positive_back:
        return "front", "high", "Front: [+front]"
    if has_positive_back and not has_positive_front:
        return "back", "high", "Back: [+back]"
    if has_positive_front and has_positive_back:
        return "central", "low", "Central (conflict): [+front, +back]"
    has_no_front_value = fr is None
    has_negative_back = bk == "-"
    if has_no_front_value and has_negative_back:
        return "front", "medium", "Front (inferred): [-back]"
    if profile.use_coronal_front_fallback:
        cor = _nonzero(feats.get("coronal"))
        ant = feats.get("anterior", "0")
        is_coronal = cor == "+"
        is_retroflex_or_rhotic = ant == "-"
        if is_coronal and not is_retroflex_or_rhotic:
            return "front", "low", "Front (inferred): CORONAL fallback"
    return "central", "low", "Central (default): no front/back specified"


def _infer_rounding(feats: dict, profile: VowelProfile) -> tuple[bool, str]:
    has_rounding = _fv(feats, "round") == "+"
    if has_rounding:
        return True, "Rounded: [+round]"
    can_use_labial_fallback = profile.use_labial_round_fallback
    has_labial = _fv(feats, "labial") == "+"
    if can_use_labial_fallback and has_labial:
        return True, "Rounded (inferred): LABIAL fallback"
    return False, "Unrounded"


_CONF_RANK = {
    "high": 3,
    "medium": 2,
    "low": 1,
}


def _vowel_grid_pos(feats: dict, profile: VowelProfile) -> VowelPlacement:
    """Return a VowelPlacement for a single vowel."""
    row, h_conf, h_reason = _infer_height(feats, profile)
    place, p_conf, p_reason = _infer_backness(feats, profile)
    rounded, r_reason = _infer_rounding(feats, profile)
    place_to_column = {
        "front": 0,
        "central": 2,
        "back": 4,
    }
    base_col = place_to_column[place]
    if rounded:
        col = base_col + 1
    else:
        col = base_col
    confidence = min(
        h_conf,
        p_conf,
        key=lambda confidence_name: _CONF_RANK[confidence_name],
    )
    reason = f"{h_reason}; {p_reason}; {r_reason}"
    return VowelPlacement(
        row=row,
        col=col,
        confidence=confidence,
        reason=reason,
    )


class VowelChartWidget(QWidget):
    """Displays vowels in an IPA-style grid: height x backness x rounding."""

    _COL_HEADERS: ClassVar[list[str]] = [
        "Front",
        "Central",
        "Back",
    ]
    _ROW_HEADERS: ClassVar[list[str]] = _ROW_LABELS
    _HDR_ACTIVE = f"color: {C['text']};"
    _HDR_INACTIVE = f"color: {C['text_dim']};"
    _ROW_ACTIVE = f"color: {C['text']}; padding-right: 4px;"
    _ROW_INACTIVE = f"color: {C['text_dim']}; padding-right: 4px;"

    def __init__(self, parent=None, *, btn_gap: int = 4):
        super().__init__(parent)
        self._buttons: dict = {}
        self._header_labels: list = []
        self._cell_containers: list = []
        self._grid = QGridLayout(self)
        self._grid.setSpacing(btn_gap)
        self._grid.setContentsMargins(0, 0, 8, 0)

    def set_headers_active(self, active: bool):
        # No dedup: ``set_vowels`` recreates the header labels on each
        # inventory load, so a stale cache would leave fresh labels
        # stuck at their initial muted style when the active state
        # happened to match across the reload.
        if active:
            header_style = self._HDR_ACTIVE
            row_style = self._ROW_ACTIVE
        else:
            header_style = self._HDR_INACTIVE
            row_style = self._ROW_INACTIVE
        for lbl, is_row in self._header_labels:
            if is_row:
                lbl.setStyleSheet(row_style)
            else:
                lbl.setStyleSheet(header_style)

    def clear(self) -> None:
        """Remove all buttons, labels, and collision containers.

        Buttons are detached (NOT destroyed) — they belong to the
        caller's segment-button pool. Detaching them BEFORE deleting
        their parent cell containers is essential, otherwise destroying
        the container would take the children with it.
        """
        for btn in self._buttons.values():
            btn.setParent(None)
        self._buttons.clear()
        while self._grid.count():
            self._grid.takeAt(0)
        for lbl, _ in self._header_labels:
            lbl.deleteLater()
        self._header_labels.clear()
        for container in self._cell_containers:
            container.deleteLater()
        self._cell_containers.clear()

    def set_vowels(self, segs: list, buttons: dict, norm_feats: dict):
        """Lay out vowel buttons in the IPA chart grid."""
        self.clear()
        self._buttons = buttons
        profile = _detect_vowel_profile(segs, norm_feats)
        hdr_font = QFont("Noto Sans", 8, QFont.Weight.Bold)
        title = QLabel("VOWELS")
        title.setFont(hdr_font)
        title.setStyleSheet(
            f"color: {C['text_dim']}; letter-spacing: 1px; padding: 2px 2px 0 2px;"
        )
        self._grid.addWidget(title, 0, 0, 1, 7)
        self._header_labels.append((title, False))
        for ci, label in enumerate(self._COL_HEADERS):
            lbl = QLabel(label)
            lbl.setFont(QFont("Noto Sans", 7))
            lbl.setStyleSheet(f"color: {C['text_dim']};")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid_col = 1 + ci * 2
            self._grid.addWidget(lbl, 1, grid_col, 1, 2)
            self._header_labels.append((lbl, False))
        occupied: dict = {}
        placements: dict = {}
        for seg in segs:
            feats = norm_feats.get(seg, {})
            placement = _vowel_grid_pos(feats, profile)
            cell_key = (placement.row, placement.col)
            placements[seg] = placement
            occupied.setdefault(cell_key, []).append(seg)
        for key in occupied:
            occupied[key].sort(
                key=lambda seg: (
                    _CONF_RANK.get(placements[seg].confidence, 0),
                    seg,
                ),
                reverse=True,
            )
        grid_row = 2
        for ri, label in enumerate(self._ROW_HEADERS):
            row_has_vowels = any((ri, col) in occupied for col in range(6))
            if not row_has_vowels:
                continue
            lbl = QLabel(label)
            lbl.setFont(QFont("Noto Sans", 7))
            lbl.setStyleSheet(f"color: {C['text_dim']}; padding-right: 4px;")
            lbl.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            lbl.setMinimumWidth(VOWEL_LABEL_W - 4)
            self._grid.addWidget(lbl, grid_row, 0)
            self._header_labels.append((lbl, True))
            for ci in range(6):
                cell_key = (ri, ci)
                cell_segs = occupied.get(cell_key, [])
                if not cell_segs:
                    continue
                if len(cell_segs) == 1:
                    seg = cell_segs[0]
                    btn = self._buttons.get(seg)
                    if btn:
                        placement = placements[seg]
                        btn.setToolTip(
                            f"/{seg}/  [{placement.confidence}]  {placement.reason}"
                        )
                        btn.show()
                        self._grid.addWidget(btn, grid_row, 1 + ci)
                    continue
                cell = QWidget()
                cell.setStyleSheet("background: transparent;")
                self._cell_containers.append(cell)
                vbox = QVBoxLayout(cell)
                vbox.setContentsMargins(0, 0, 0, 0)
                vbox.setSpacing(1)
                for seg in cell_segs:
                    btn = self._buttons.get(seg)
                    if btn:
                        placement = placements[seg]
                        btn.setToolTip(
                            f"/{seg}/  [{placement.confidence}]  {placement.reason}"
                        )
                        btn.show()
                        vbox.addWidget(btn)
                self._grid.addWidget(cell, grid_row, 1 + ci)
            grid_row += 1
