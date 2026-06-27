"""Pin the singleton/stranding gate on the laryngeal rescue in
:py:func:`phonology_shared.chart.consonants.group_segments`.

The "Laryngeals" row (h / ɦ / ʔ pulled out of their manner classes) is
a convenience regroup: it must not make the display worse by leaving a
singleton. A lone glottal segment stays in its manner home (h/ɦ among
the fricatives, ʔ among the plosives); the row forms only from two or
more members and only when peeling does not strand a source group as a
singleton.
"""

from __future__ import annotations

from phonology_shared.chart.consonants import group_segments


def _fric(**kw: str) -> dict[str, str]:
    base = {"consonantal": "+", "continuant": "+", "sonorant": "-"}
    base.update(kw)
    return base


def _stop(**kw: str) -> dict[str, str]:
    base = {
        "consonantal": "+",
        "continuant": "-",
        "sonorant": "-",
        "nasal": "-",
        "delrel": "-",
    }
    base.update(kw)
    return base


# Glottal segments: a laryngeal feature (spreadgl/constrgl) and no oral
# place, so _is_laryngeal_candidate fires.
def _h() -> dict[str, str]:
    return _fric(spreadgl="+")  # voiceless glottal fricative


def _h_voiced() -> dict[str, str]:
    return _fric(voice="+", spreadgl="+")  # ɦ-like


def _glottal_stop() -> dict[str, str]:
    return _stop(constrgl="+")  # ʔ-like


def test_lone_glottal_fricative_stays_with_the_oral_fricative() -> None:
    # The Hindi case: peeling the glottal fricative would strand the
    # single oral fricative, so both stay in Fricatives, no Laryngeals.
    groups = group_segments({"f": _fric(labial="+"), "ɦ": _h_voiced()})
    assert "Laryngeals" not in groups
    assert set(groups["Fricatives"]) == {"f", "ɦ"}


def test_single_glottal_with_a_surviving_source_still_no_row() -> None:
    # Source would survive the peel (3 oral fricatives remain), but a
    # single laryngeal is not worth its own row: it stays put.
    inv = {
        "f": _fric(labial="+"),
        "x": _fric(dorsal="+"),
        "θ": _fric(coronal="+", anterior="+", strident="-"),
        "h": _h(),
    }
    groups = group_segments(inv)
    assert "Laryngeals" not in groups
    assert "h" in groups["Fricatives"]


def test_two_glottals_from_surviving_sources_form_the_row() -> None:
    inv = {
        "f": _fric(labial="+"),
        "x": _fric(dorsal="+"),
        "p": _stop(labial="+"),
        "t": _stop(coronal="+"),
        "h": _h(),
        "ʔ": _glottal_stop(),
    }
    groups = group_segments(inv)
    assert set(groups["Laryngeals"]) == {"h", "ʔ"}
    assert "h" not in groups.get("Fricatives", [])
    assert "ʔ" not in groups.get("Plosives", [])


def test_three_glottals_form_the_row() -> None:
    # Two plosives so peeling ʔ does not strand the plosive row.
    inv = {
        "f": _fric(labial="+"),
        "x": _fric(dorsal="+"),
        "p": _stop(labial="+"),
        "t": _stop(coronal="+"),
        "h": _h(),
        "ɦ": _h_voiced(),
        "ʔ": _glottal_stop(),
    }
    groups = group_segments(inv)
    assert set(groups["Laryngeals"]) == {"h", "ɦ", "ʔ"}


def test_strand_guard_keeps_h_with_the_lone_oral_fricative() -> None:
    # Peeling h would strand the single oral fricative /s/, so h stays
    # in Fricatives; ʔ alone is then not enough for a row and stays a
    # plosive. This is the ilokano/indonesian/tobabatak shape.
    inv = {
        "s": _fric(coronal="+", strident="+"),
        "p": _stop(labial="+"),
        "t": _stop(coronal="+"),
        "k": _stop(dorsal="+"),
        "h": _h(),
        "ʔ": _glottal_stop(),
    }
    groups = group_segments(inv)
    assert "Laryngeals" not in groups
    assert set(groups["Fricatives"]) == {"s", "h"}
    assert "ʔ" in groups["Plosives"]
