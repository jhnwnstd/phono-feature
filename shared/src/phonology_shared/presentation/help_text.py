"""User-facing help copy for the Segments pane, shared by both UIs.

The Segments pane exposes two click-to-open help windows: the pane's
``SEGMENTS`` title explains how to read the consonant AND vowel displays
at a philosophy level, and the ``Vowels`` chart title drills into the
specific feature-to-space placement rules. Keeping the copy here makes
it the single source of truth: the desktop imports these constants
directly, and ``web/scripts/build.py`` bakes them into an inline
``application/json`` block the web reads (mirroring the status-text
relay), so the two frontends can never show different wording.

The bodies are a conservative HTML subset (``<p>``, ``<b>``, ``<ul>``,
``<li>``) that renders identically in a Qt rich-text widget and in the
browser. Feature notation uses plain brackets (``[-tense]``) so it needs
no markup. The wording is grounded in the actual heuristics:

* consonants: manner grouping + place-ordering + size-driven
  breakout/merge, all from encoded features
  (:mod:`phonology_shared.chart.consonants`);
* vowels: the height/backness/rounding inference and the low-vowel
  Near-open split (:mod:`phonology_shared.chart.vowels`), the Open-row
  migration (:mod:`phonology_shared.chart.vowel_geometry.display_slots`).
"""

from __future__ import annotations

#: Title of the ``SEGMENTS`` help window.
SEGMENTS_HELP_TITLE: str = "How to read the segment displays"

#: Body of the ``SEGMENTS`` help window.
SEGMENTS_HELP_HTML: str = (
    "<p><i>Right-click any segment button to copy it.</i></p>"
    "<p>The display uses only the encoded features for each segment. It does"
    " not infer features from a symbol, a diacritic, or the segment's usual"
    " pronunciation. If the features do not encode a distinction, the chart"
    " cannot show that distinction.</p>"
    "<p>The layout is a practical display aid, not a full phonetic or"
    " theoretical analysis. It keeps every segment visible, even when the"
    " encoded features are incomplete or hard to place. Such segments fall"
    " into one of two catch-all groups: consonant-like segments join"
    " <b>Contoids</b>, shown below the consonant groups, and vowel-like"
    " segments join <b>Vocoids</b>, shown below the vowel chart.</p>"
    "<p><b>Consonants</b> are grouped by manner of articulation. Within each"
    " group, they are ordered by place of articulation from front to back."
    " The display also adjusts group size to keep the layout readable. A"
    " class with enough members can form its own group. For example,"
    " sibilants may split from fricatives, and ejectives or implosives may"
    " split from plosives. A class with too few members folds into a broader"
    " group, such as Vibrants, Rhotics, or Liquids. The same class may"
    " therefore stand alone in one inventory and merge into a broader group"
    " in another.</p>"
    "<p><b>Vowels</b> are placed from their encoded height, backness,"
    " rounding, and related features. Their positions are useful display"
    " positions, not exact measurements of pronunciation. Click the"
    " <b>Vowels</b> label above the chart to see the placement rules.</p>"
)

#: Title of the ``Vowels`` help window.
VOWELS_HELP_TITLE: str = "How vowels are placed"

#: Body of the ``Vowels`` help window.
VOWELS_HELP_HTML: str = (
    "<p>The chart places vowels using their encoded features. It does not"
    " claim to show each vowel's exact phonetic value. Even if a vowel has"
    " missing or contradictory features, the chart places it at a fixed"
    " fallback position.</p>"
    "<p><b>Height (rows)</b><br>A vowel's height determines its row. Tense"
    " and ATR features refine the row only when the inventory uses those"
    " contrasts.</p>"
    "<ul>"
    "<li>[+high, -low] maps to Close. If it is [-tense], it maps to"
    " Near-close.</li>"
    "<li>[-high, -low] maps to the mid region. If it is [+tense], it maps to"
    " Close-mid. If it is [-tense], it maps to Open-mid. If it has no tense"
    " or ATR value, it maps to Mid.</li>"
    "<li>[-high, +low] maps to Open. If it is [-tense], [-ATR], or [+RTR],"
    " and the inventory uses tense or ATR contrasts, it maps to Near-open."
    " If it is [+tense] or has no tense or ATR value, it remains Open.</li>"
    "</ul>"
    "<p>If the bottom Open row has no front vowel, a central low vowel such"
    " as lone /a/ can occupy the bottom-left corner instead of the"
    " bottom-center.</p>"
    "<p><b>Backness (columns)</b><br>A vowel's backness determines its"
    " column. [+front] maps to Front. [+back] maps to Back. [-front,"
    " -back] maps to Central. [-back] by itself does not map to Front.</p>"
    "<p><b>Rounding</b><br>Rounded and unrounded vowels with the same height"
    " and backness appear side by side. The unrounded vowel appears on the"
    " left. The rounded vowel appears on the right. A vowel with no rounding"
    " feature will occupy the center of its column.</p>"
    "<p><b>Relative features</b><br>Relative features adjust the base"
    " position.</p>"
    "<ul>"
    "<li>[+raised] moves up one row.</li>"
    "<li>[+lowered] moves down one row.</li>"
    "<li>[+advanced] moves one column forward.</li>"
    "<li>[+retracted] moves one column backward.</li>"
    "<li>[+centralized] moves toward Central.</li>"
    "</ul>"
    "<p>Vowels encoded with opposing relative features stay in their base"
    " position.</p>"
    "<p><b>Secondary features</b><br>Length, nasality, rhoticity, phonation,"
    " and tone do not change a vowel's row or column. Two vowels that differ"
    " in exactly one of these features share one segmented capsule. If two"
    " such contrasts are present, the vowels form a small two-by-two"
    " capsule. Vowels that share a position but differ in more complex ways"
    " stack.</p>"
    "<p><b>Diphthongs</b> are listed below the vowel chart.</p>"
)
