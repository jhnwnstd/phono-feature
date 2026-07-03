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

#: Body of the ``SEGMENTS`` help window: the shared philosophy behind
#: both the consonant groups and the vowel chart. The substance-free
#: framing is stated ONCE here (it governs everything) so the Vowels
#: window need not repeat it.
SEGMENTS_HELP_HTML: str = (
    "<p><i>Copy any segment by right clicking the button.</i></p>"
    "<p>Every grouping and position is decided only by a segment's"
    " encoded features. The symbol and its diacritics are not used to"
    " infer features. If a distinction is not encoded in the features,"
    " the display cannot show it.</p>"
    "<p>The display is designed to cover most use cases rather than every"
    " possible analysis. Treat display groupings as a representational"
    " convenience, not as a theoretical claim. Anything the features cannot "
    " place stays visible in a catch-all group: Contoids appear below the "  
    " consonants, and Vocoids appear below the vowel chart.</p>"
    "<p><b>Consonants</b> are grouped by manner of articulation and,"
    " within each group, ordered by place from front to back. The groups"
    " aim to be reasonably canonical while keeping the layout balanced, so"
    " no single group becomes visually dominant. A class with enough"
    " members in the inventory is shown on its own. For example, sibilants"
    " may split from fricatives, and ejectives or implosives may split"
    " from plosives. A class that is too small to stand alone is folded"
    " into a broader cover label, such as Vibrants, Rhotics, or Liquids."
    " The same class can therefore stand alone in one inventory and merge"
    " into a broader group in another.</p>"
    "<p><b>Vowels</b> follow the same principle. Mapping discrete features"
    " onto a static, continuous vowel space requires representational"
    " shortcuts. A vowel's position is therefore a guide and a soft"
    " validation check, not the definitive phonetic vowel space for a"
    " language's speakers. Click the <b>Vowels</b> label above the chart"
    " for the specific placement rules.</p>"
)

#: Title of the ``Vowels`` help window.
VOWELS_HELP_TITLE: str = "How vowels are placed"

#: Body of the ``Vowels`` help window: the specific feature-to-space
#: placement rules (height, the low-vowel Near-open split, backness,
#: relative features, rounding, secondary-feature capsules, diphthongs,
#: and the lone-low-vowel corner).
VOWELS_HELP_HTML: str = (
    "<p>Chart placement does not imply a vowel's exact phonetic value. If a"
    " vowel has missing or contradictory features, the chart places it at a"
    " stable low-confidence anchor. That anchor is a display fallback, not a"
    " phonetic claim.</p>"
    "<p><b>Height (rows)</b><br>A vowel's height determines its row. A"
    " vowel with [+high] is placed on the Close row. A vowel with [+low]"
    " is placed on the Open row. A vowel with [-high, -low] is placed in"
    " the mid region. If the inventory uses tense or ATR contrasts, these"
    " rows are refined. A [-tense] high vowel is placed on the Near-close"
    " row. A [+tense] mid vowel is placed on the Close-mid row. A [-tense]"
    " mid vowel is placed on the Open-mid row. A mid vowel with no tense"
    " or ATR value is placed on the plain Mid row.</p>"
    "<p><b>Low vowels and /a/</b><br>Low vowels normally remain on the"
    " Open row. This includes central /a/, which is represented as"
    " [-front, -back]. If a low vowel is also [-tense], [-ATR], or [+RTR],"
    " and the inventory uses tense or ATR contrasts, the vowel is moved up"
    " to the Near-open row. A [+tense] low vowel, or a low vowel with no"
    " tense or ATR value, stays on the Open row. This rule is"
    " theory-sensitive. Some analyses keep all low vowels on the Open row,"
    " but the split is enabled here by default.</p>"
    "<p><b>Backness (columns)</b><br>A vowel's backness determines its"
    " column. A vowel with [+front] is placed in the Front column. A vowel"
    " with [+back] is placed in the Back column. A vowel with [-front,"
    " -back] is placed in the Central column. The feature [-back] by"
    " itself is not treated as [+front].</p>"
    "<p><b>Relative features</b> adjust a vowel's base position. [+raised]"
    " moves a vowel up one row. [+lowered] moves it down one row."
    " [+advanced] moves it one column forward. [+retracted] moves it one"
    " column backward. [+centralized] moves it toward the Central column."
    " A feature and its opposite cancel each other.</p>"
    "<p><b>Rounded</b> and <b>unrounded</b> vowels with the same height and"
    " backness are drawn side by side, with the unrounded vowel on the"
    " left and the rounded vowel on the right. A vowel with no rounding"
    " feature is centered on its backness anchor.</p>"
    "<p>Other <b>secondary features</b> like length, nasality, rhoticity,"
    " phonation, tone, and pharyngealization do not create new chart"
    " positions. Two vowels that differ in exactly one of these features"
    " are shown as one segmented capsule. If two such contrasts are"
    " present, the chart shows a small two-by-two capsule. Vowels that"
    " share a position but differ in more complex ways are stacked.</p>"
    "<p><b>Diphthongs</b> are not placed inside the vowel space. They are"
    " shown below the chart.</p>"
    "<p>A lone low vowel is handled specially. If the Open row has no"
    " front vowel, a single low vowel is drawn in the bottom-left corner"
    " instead of the bottom center edge.</p>"
)
