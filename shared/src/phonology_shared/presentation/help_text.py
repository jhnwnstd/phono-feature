"""User-facing help copy for the Segments and Features panes, shared by
both UIs.

Three click-to-open help windows. The ``SEGMENTS`` pane title explains
how to read the consonant and vowel displays at a general level. The
``Vowels`` chart title gives the specific feature-to-space placement
rules. The ``FEATURES`` pane title explains readout mode, the
feature-to-segment query, and strict versus underspecified matching.
Keeping the copy here makes it the single source of truth: the desktop
imports these constants directly, and ``web/scripts/build.py`` bakes
them into an inline ``application/json`` block the web reads (mirroring
the status-text relay), so the two frontends can never show different
wording.

The bodies are a conservative HTML subset (``<p>``, ``<b>``, ``<i>``,
``<br>``, ``<ul>``, ``<li>``) that renders identically in a Qt rich-text
widget and in the browser. Feature notation uses plain brackets
(``[-tense]``) so it needs no markup. The wording is grounded in the
actual heuristics:

* consonants: existential-reach routing (a contour segment renders in
  every manner group some phase of it reaches), manner grouping +
  place-ordering + size-driven breakout/merge, all from specified
  features (:mod:`phonology_shared.chart.consonants`);
* vowels: the height/backness/rounding inference and the low-vowel
  Near-open split (:mod:`phonology_shared.chart.vowels`), the Open-row
  migration (:mod:`phonology_shared.chart.vowel_geometry.display_slots`);
* features: the readout badges, the feature-to-segment query, and strict
  versus underspecified matching
  (:mod:`phonology_shared.theory.feature_engine`), plus feature grouping
  and glossary links
  (:mod:`phonology_shared.presentation.feature_metadata`).
"""

from __future__ import annotations

#: Title of the ``SEGMENTS`` help window.
SEGMENTS_HELP_TITLE: str = "How to read the segment displays"

#: Body of the ``SEGMENTS`` help window.
SEGMENTS_HELP_HTML: str = (
    "<p><i>Right-click any segment to copy it.</i></p>"
    "<p>The display uses only the specified features of each segment. It does"
    " not infer features from a symbol, a diacritic, or the segment's"
    " conventional pronunciation. If the specified features do not"
    " distinguish two segments, the display cannot show that distinction.</p>"
    "<p>The layout is a practical display aid, not a phonetic or"
    " theoretical analysis. The layout keeps every segment visible, even when the"
    " specified features are incomplete or hard to place. Such segments fall"
    " into one of two catch-all groups: consonant-like segments join"
    " <b>Contoids</b>, shown below the consonant groups, and vowel-like"
    " segments join <b>Vocoids</b>, shown below the vowel chart.</p>"
    "<p><b>Consonants</b> are grouped by manner of articulation. Within each"
    " group, consonants are ordered by place of articulation from the front to back"
    " of the mouth."
    " A segment whose specified value for a feature changes across the"
    " segment is a member of every group that some part of it matches, and appears in"
    " each of those groups. A small count on the segment marks how many"
    " groups show it; selecting it in one group selects it everywhere.</p>"
    "<p>The display also adjusts how finely a group is divided, to keep"
    " the layout readable. A class with enough members can form its own"
    " sub-group: sibilants may split from fricatives, and ejectives or"
    " implosives may split from plosives. A sub-group with too few members"
    " folds back into its parent group. Only the level of detail changes"
    " between inventories; a segment always appears within the group its"
    " features place it in.</p>"
    "<p><b>Vowels</b> are placed using their specified height, backness,"
    " rounding, and related features. The vowels' positions are useful display"
    " positions, not exact representations of phonetic reality.</p>"
)

#: Title of the ``Vowels`` help window.
VOWELS_HELP_TITLE: str = "How vowels are placed"

#: Body of the ``Vowels`` help window.
VOWELS_HELP_HTML: str = (
    "<p>Vowel placement on the chart is determined by the vowel"
    " segment's specified features."
    " The vowel placement is not a claim about each vowel's exact"
    " phonetic position. Even"
    " vowels with missing or contradictory features can be placed somewhere"
    " on the chart.</p>"
    "<p><b>Height (rows)</b><br>A vowel's height determines its row. Tense"
    " and ATR features refine row placement only when the inventory uses"
    " those features.</p>"
    "<ul>"
    "<li>[+high, -low] maps to Close. If it is [-tense], it maps to"
    " Near-close.</li>"
    "<li>[-high, -low] maps to the mid region. If it is [+tense], it maps to"
    " Close-mid. If it is [-tense], it maps to Open-mid. If it has no"
    " specified tense or ATR feature, it maps to Mid.</li>"
    "<li>[-high, +low] maps to Open. If it is [-tense], [-ATR], or [+RTR],"
    " and the inventory uses tense or ATR contrasts, it maps to Near-open."
    " If it is [+tense] or has no specified tense or ATR feature, it remains"
    " Open.</li>"
    "</ul>"
    "<p>If the Open row has no front vowel, then a low central vowel such"
    " as /a/ can occupy the Front column instead of the Center column.</p>"
    "<p><b>Backness (columns)</b><br>A vowel's backness determines its"
    " column. [+front] maps to Front. [+back] maps to Back. [-front,"
    " -back] maps to Central. [-back] by itself does not map to Front.</p>"
    "<p><b>Rounding</b><br>Rounded and unrounded vowels with the same height"
    " and backness appear side by side. The unrounded vowel appears on the"
    " left. The rounded vowel appears on the right. A vowel with no rounding"
    " feature occupies the center of its column.</p>"
    "<p><b>Relative features</b> adjust the base position.</p>"
    "<ul>"
    "<li>[+raised] moves up one row.</li>"
    "<li>[+lowered] moves down one row.</li>"
    "<li>[+advanced] moves one column forward.</li>"
    "<li>[+retracted] moves one column backward.</li>"
    "<li>[+centralized] moves toward Central.</li>"
    "</ul>"
    "<p>Vowels specified with opposing relative features stay in their original"
    " position.</p>"
    "<p><b>Secondary features</b><br>Length, nasality, rhoticity, phonation,"
    " and tone do not change a vowel's row or column. Two vowels that differ"
    " in exactly one of these features share one segmented capsule. If two"
    " such contrasts are present, the vowels form a small two-by-two"
    " capsule. Vowels that share a position but differ in more complex ways"
    " stack.</p>"
    "<p><b>Diphthongs</b> are listed below the vowel chart.</p>"
)

#: Title of the ``FEATURES`` help window.
FEATURES_HELP_TITLE: str = "How to read and query features"

#: Body of the ``FEATURES`` help window.
FEATURES_HELP_HTML: str = (
    "<p>The Features pane has two modes. When you select a segment, the"
    " pane reports the segment's feature values. When you set a"
    " feature specification, the pane queries the inventory for segments"
    " that match that specification.</p>"
    "<p>If a segment carries a sequence of values on a feature, the"
    " feature reports ± for that segment. A prenasalized stop, for"
    " example, is [+nasal] at its start and [-nasal] at its release, so"
    " its nasal feature reads ± and the segment matches a query for"
    " either value.</p>"
    "<p><b>Feature groups and names</b><br>Features are grouped by"
    " phonological role: Major Class, Laryngeal, Manner, Place,"
    " Tongue-Root / Pharyngeal, and Prosodic. Any inventory feature"
    " outside these groups appears as Other. An underlined feature name"
    " links to an external glossary definition.</p>"
    "<p><b>Querying by feature</b><br>When + or − is selected for a feature,"
    " that specification is added to the query. Matching segments"
    " highlight in the Segments pane.</p>"
    "<p><b>Reading segments</b><br>When one or more segments are selected in"
    " the Segments pane, each feature reports the specified value"
    " across the current segment selection.</p>"
    "<ul>"
    "<li>+ means every selected segment is specified [+] for that"
    " feature.</li>"
    "<li>− means every selected segment is specified [-] for that"
    " feature.</li>"
    "<li>± means the selection holds both [+] and [-] for that feature:"
    " either the selected segments split between the two values, or a"
    " selected segment itself carries both across its sequence.</li>"
    "<li>· means the selected segments neither share one specified value"
    " nor split between both values. Either every selected segment leaves"
    " the feature unspecified, or some selected segments specify one value"
    " while the rest leave it unspecified.</li>"
    "</ul>"
    "<p><b>Natural class completion</b><br>When the selected segments do"
    " not form a natural class under the current matching mode, the"
    " Segments pane outlines in blue the additional segments that complete"
    " the smallest natural class containing the selection.</p>"
    "<p><b>Strict and underspecified matching</b><br>The ≈ button controls"
    " how the query treats unspecified features.</p>"
    "<p>In strict matching, a [+F] query matches only segments explicitly"
    " specified [+F], and a [-F] query matches only segments explicitly"
    " specified [-F]. An unspecified or absent feature does not match"
    " either query.</p>"
    "<p>In underspecified matching, an unspecified or absent feature can"
    " match either a [+F] or [-F] query.</p>"
)
