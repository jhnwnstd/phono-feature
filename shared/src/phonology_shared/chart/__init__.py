"""IPA chart layout: consonant manner-class grouping and vowel chart
placement.

Every module answers the same question for different segment types:
"given an inventory, where does each segment sit on the IPA chart?"
The consonant side returns manner-class groupings; the vowel side
returns trapezoid/triangle coordinates.

Module map (low layer to high):

* ``vowel_space``    the abstract vowel-space coordinate system
                     (axes, anchors, trapezoid widths). Foundation,
                     inventory-independent, derived from pixels.
* ``vowels``         vowel feature-to-placement INFERENCE; sits on
                     ``vowel_space``.
* ``vowel_geometry`` the render-ready vowel geometry pipeline
                     (silhouette, cells, furniture); sits on
                     ``vowel_space`` for coordinates and ``vowels``
                     for placement types. See its package docstring
                     for the internal layer table.
* ``consonants``     consonant manner-class GROUPING + per-segment
                     feature derivation.
* ``segment_classes`` per-class counts and hard-cap POLICY (vowel /
                     consonant / tone), kept apart from grouping.
"""
