"""
gui/vowel_chart.py
IPA-style vowel trapezoid chart widget.

Maps vowel segments onto a height x backness x rounding grid using
normalised phonological features.  Placement is inventory-sensitive:
a VowelProfile is computed once per inventory to determine which
features are active, so fallback logic (e.g. coronal→front, ATR→height)
only fires when the inventory actually lacks the direct feature.

Each placement carries a confidence level ("high", "medium", "low") and
a human-readable reason string, surfaced as tooltips on the buttons.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from gui.palette import C

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

VOWEL_LABEL_W = 72  # px — fits "Near-close" at 7pt with padding

# ---------------------------------------------------------------------------
# Height classification: (label, High, Low, Tense/ATR)
#   None in the Tense slot means "don't care" (Open vowels).
# ---------------------------------------------------------------------------

_VOWEL_HEIGHT: list = [
    ("Close", "+", "-", "+"),
    ("Near-close", "+", "-", "-"),
    ("Close-mid", "-", "-", "+"),
    ("Open-mid", "-", "-", "-"),
    ("Near-open", "-", "+", "-"),
    ("Open", "-", "+", None),
]

_ROW_LABELS = [label for label, *_ in _VOWEL_HEIGHT]

# ---------------------------------------------------------------------------
# Inventory profile — computed once per vowel set
# ---------------------------------------------------------------------------


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
        return self.has_coronal and not self.has_front

    @property
    def has_height_sub_distinction(self) -> bool:
        """True if the inventory uses ATR or Tense to split height tiers."""
        return self.has_atr or self.has_tense

    @property
    def use_labial_round_fallback(self) -> bool:
        """Use LABIAL as a rounding proxy only when Round is absent."""
        return self.has_labial and not self.has_round


def detect_vowel_profile(segs: list, norm_feats: dict) -> VowelProfile:
    """Scan the vowel segments to determine which features are in play."""
    active: set[str] = set()
    for seg in segs:
        for feat, val in norm_feats.get(seg, {}).items():
            if val != "0":
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


# ---------------------------------------------------------------------------
# Placement result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VowelPlacement:
    row: int
    col: int
    confidence: str  # "high" | "medium" | "low"
    reason: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fv(feats: dict, key: str) -> str:
    """Feature value, defaulting to '0'."""
    return feats.get(key, "0")


def _nonzero(val: str | None) -> str | None:
    """Return *val* only if it carries real feature information ('+' or '-')."""
    return val if val and val != "0" else None


# ---------------------------------------------------------------------------
# Inference: height
# ---------------------------------------------------------------------------


def _infer_height(feats: dict, profile: VowelProfile) -> tuple[int, str, str]:
    """Return (row, confidence, reason).

    Conservative policy for low vowels: [-high, +low] defaults to Open.
    Near-open is only used when ATR/Tense is active in the inventory AND
    the vowel is explicitly [-ATR/-tense], giving real evidence for a
    split.  Same conservatism for Near-close vs Close.
    """
    hi = _fv(feats, "high")
    lo = _fv(feats, "low")
    atr_tn = _nonzero(feats.get("tense")) or _nonzero(feats.get("atr"))

    if hi == "+" and lo == "-":
        if profile.has_height_sub_distinction and atr_tn == "-":
            return 1, "medium", "Near-close: [+high, -low, -tense/ATR]"
        if atr_tn == "+":
            return 0, "high", "Close: [+high, -low, +tense/ATR]"
        return 0, "high", "Close: [+high, -low]"

    if hi == "-" and lo == "+":
        if profile.has_height_sub_distinction and atr_tn == "-":
            return 4, "medium", "Near-open: [-high, +low, -tense/ATR]"
        return 5, "high", "Open: [-high, +low]"

    if hi == "-" and lo == "-":
        if atr_tn == "+":
            return 2, "medium", "Close-mid: [-high, -low, +tense/ATR]"
        if atr_tn == "-":
            return 3, "medium", "Open-mid: [-high, -low, -tense/ATR]"
        return 3, "low", "Open-mid (default): [-high, -low], no tense/ATR"

    return 3, "low", "Open-mid (default): underspecified height"


# ---------------------------------------------------------------------------
# Inference: backness
# ---------------------------------------------------------------------------


def _infer_backness(
    feats: dict, profile: VowelProfile
) -> tuple[str, str, str]:
    """Return (place, confidence, reason).  place is 'front'|'central'|'back'."""
    fr = _nonzero(feats.get("front"))
    bk = _nonzero(feats.get("back"))

    # Explicit front/back
    if fr == "+" and bk != "+":
        return "front", "high", "Front: [+front]"
    if bk == "+" and fr != "+":
        return "back", "high", "Back: [+back]"
    if fr == "+" and bk == "+":
        return "central", "low", "Central (conflict): [+front, +back]"

    # [-back] as front inference — many systems encode frontness this way
    if fr is None and bk == "-":
        return "front", "medium", "Front (inferred): [-back]"

    # Coronal fallback — only when the inventory lacks an explicit Front feature
    if profile.use_coronal_front_fallback:
        cor = _nonzero(feats.get("coronal"))
        ant = feats.get("anterior", "0")
        # Retroflex/rhotic coronals (anterior:-) do not imply frontness
        if cor == "+" and ant != "-":
            return "front", "low", "Front (inferred): CORONAL fallback"

    return "central", "low", "Central (default): no front/back specified"


# ---------------------------------------------------------------------------
# Inference: rounding
# ---------------------------------------------------------------------------


def _infer_rounding(feats: dict, profile: VowelProfile) -> tuple[bool, str]:
    if _fv(feats, "round") == "+":
        return True, "Rounded: [+round]"
    # Labial fallback — some systems mark rounding under LABIAL
    if profile.use_labial_round_fallback and _fv(feats, "labial") == "+":
        return True, "Rounded (inferred): LABIAL fallback"
    return False, "Unrounded"


# ---------------------------------------------------------------------------
# Composed placement
# ---------------------------------------------------------------------------

_CONF_RANK = {"high": 3, "medium": 2, "low": 1}


def vowel_grid_pos(feats: dict, profile: VowelProfile) -> VowelPlacement:
    """Return a VowelPlacement for a single vowel."""
    row, h_conf, h_reason = _infer_height(feats, profile)
    place, p_conf, p_reason = _infer_backness(feats, profile)
    rounded, r_reason = _infer_rounding(feats, profile)

    base_col = {"front": 0, "central": 2, "back": 4}[place]
    col = base_col + (1 if rounded else 0)

    confidence = min(h_conf, p_conf, key=lambda c: _CONF_RANK[c])
    reason = f"{h_reason}; {p_reason}; {r_reason}"

    return VowelPlacement(
        row=row, col=col, confidence=confidence, reason=reason
    )


# ---------------------------------------------------------------------------
# VowelChartWidget
# ---------------------------------------------------------------------------


class VowelChartWidget(QWidget):
    """Displays vowels in an IPA-style grid: height x backness x rounding."""

    _COL_HEADERS = ["Front", "Central", "Back"]
    _ROW_HEADERS = _ROW_LABELS

    def __init__(self, parent=None, *, btn_gap: int = 4):
        super().__init__(parent)
        self._buttons: dict = {}
        self._header_labels: list = []
        self._cell_containers: list = []
        self._grid = QGridLayout(self)
        self._grid.setSpacing(btn_gap)
        self._grid.setContentsMargins(0, 0, 8, 0)

    _HDR_ACTIVE = f"color: {C['text']};"
    _HDR_INACTIVE = f"color: {C['text_dim']};"
    _ROW_ACTIVE = f"color: {C['text']}; padding-right: 4px;"
    _ROW_INACTIVE = f"color: {C['text_dim']}; padding-right: 4px;"

    def set_headers_active(self, active: bool):
        hdr = self._HDR_ACTIVE if active else self._HDR_INACTIVE
        row = self._ROW_ACTIVE if active else self._ROW_INACTIVE
        for lbl, is_row in self._header_labels:
            lbl.setStyleSheet(row if is_row else hdr)

    def clear(self):
        """Remove all buttons, labels, and collision containers."""
        while self._grid.count():
            self._grid.takeAt(0)
        for btn in self._buttons.values():
            btn.deleteLater()
        self._buttons.clear()
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

        # Detect which features this inventory actually uses for vowels
        profile = detect_vowel_profile(segs, norm_feats)

        hdr_font = QFont("Noto Sans", 8, QFont.Weight.Bold)

        title = QLabel("VOWELS")
        title.setFont(hdr_font)
        title.setStyleSheet(
            f"color: {C['text_dim']}; letter-spacing: 1px;"
            " padding: 2px 2px 0 2px;"
        )
        self._grid.addWidget(title, 0, 0, 1, 7)
        self._header_labels.append((title, False))

        for ci, label in enumerate(self._COL_HEADERS):
            lbl = QLabel(label)
            lbl.setFont(QFont("Noto Sans", 7))
            lbl.setStyleSheet(f"color: {C['text_dim']};")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._grid.addWidget(lbl, 1, 1 + ci * 2, 1, 2)
            self._header_labels.append((lbl, False))

        occupied: dict = {}
        placements: dict = {}
        for seg in segs:
            feats = norm_feats.get(seg, {})
            placement = vowel_grid_pos(feats, profile)
            placements[seg] = placement
            occupied.setdefault((placement.row, placement.col), []).append(seg)

        # Sort collision cells by confidence then symbol for stable display
        for key in occupied:
            occupied[key].sort(
                key=lambda s: (_CONF_RANK.get(placements[s].confidence, 0), s),
                reverse=True,
            )

        grid_row = 2
        for ri, label in enumerate(self._ROW_HEADERS):
            if not any((ri, c) in occupied for c in range(6)):
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
                cell_segs = occupied.get((ri, ci), [])
                if not cell_segs:
                    continue
                if len(cell_segs) == 1:
                    btn = self._buttons.get(cell_segs[0])
                    if btn:
                        p = placements[cell_segs[0]]
                        btn.setToolTip(
                            f"/{cell_segs[0]}/  [{p.confidence}]  {p.reason}"
                        )
                        btn.show()
                        self._grid.addWidget(btn, grid_row, 1 + ci)
                else:
                    cell = QWidget()
                    cell.setStyleSheet("background: transparent;")
                    self._cell_containers.append(cell)
                    vbox = QVBoxLayout(cell)
                    vbox.setContentsMargins(0, 0, 0, 0)
                    vbox.setSpacing(1)
                    for seg in cell_segs:
                        btn = self._buttons.get(seg)
                        if btn:
                            p = placements[seg]
                            btn.setToolTip(
                                f"/{seg}/  [{p.confidence}]  {p.reason}"
                            )
                            btn.show()
                            vbox.addWidget(btn)
                    self._grid.addWidget(cell, grid_row, 1 + ci)

            grid_row += 1
