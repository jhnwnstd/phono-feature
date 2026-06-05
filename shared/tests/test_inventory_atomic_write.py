"""Atomic-write hardening contract.

These tests pin three properties added in the boundary tightening
refactor:

  1. NaN / Infinity in input raises :py:class:`ValueError` BEFORE
     any temp file touches the filesystem (symmetric with the read
     path, which rejects the same literals via
     :py:func:`_reject_non_finite`).
  2. The function accepts :py:class:`os.PathLike` paths (e.g.
     :py:class:`pathlib.Path`) -- no string coercion required at
     call sites.
  3. JSON is pre-encoded so a serialization error never leaves a
     temp file behind in the target directory.

The previously existing atomicity contract (no truncation on
failure, tmp cleanup on exception, replace + dir fsync) is covered
in :py:mod:`desktop/tests/test_inventory_contract.py` -- these
tests do not duplicate that coverage.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from phonology_shared.data.inventory import atomic_write_json


def _tmp_files(directory: pathlib.Path) -> list[pathlib.Path]:
    """List leftover ``.tmp_inv_*`` siblings of ``directory``."""
    return [p for p in directory.iterdir() if p.name.startswith(".tmp_inv_")]


def test_nan_rejected_before_any_temp_file(tmp_path: pathlib.Path) -> None:
    """``float('nan')`` in the data triggers ``json.dumps``'s
    ``allow_nan=False`` path, which raises ``ValueError`` BEFORE
    :py:func:`tempfile.mkstemp` is called. No temp file leaks into
    the destination directory."""
    target = tmp_path / "out.json"
    with pytest.raises(ValueError) as ex:
        atomic_write_json(target, {"a": float("nan")})
    assert (
        "nan" in str(ex.value).lower()
        or "not json compliant" in str(ex.value).lower()
    )
    assert _tmp_files(tmp_path) == []
    assert not target.exists()


def test_positive_infinity_rejected(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "out.json"
    with pytest.raises(ValueError):
        atomic_write_json(target, {"a": float("inf")})
    assert _tmp_files(tmp_path) == []


def test_negative_infinity_rejected(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "out.json"
    with pytest.raises(ValueError):
        atomic_write_json(target, {"a": float("-inf")})
    assert _tmp_files(tmp_path) == []


def test_accepts_pathlib_path(tmp_path: pathlib.Path) -> None:
    """``PathLike[str]`` works without explicit ``str()`` at the
    call site; the function converts via :py:func:`os.fspath`."""
    target = tmp_path / "out.json"
    atomic_write_json(target, {"hello": "world"})
    assert target.is_file()
    assert json.loads(target.read_text(encoding="utf-8")) == {"hello": "world"}


def test_accepts_plain_str_path(tmp_path: pathlib.Path) -> None:
    """The pre-existing string-path contract still works."""
    target = tmp_path / "out.json"
    atomic_write_json(str(target), {"hello": "world"})
    assert target.is_file()


def test_unserializable_object_no_temp_leak(
    tmp_path: pathlib.Path,
) -> None:
    """A type ``json.dumps`` cannot serialize raises BEFORE the temp
    file is created, thanks to the pre-encode step."""
    target = tmp_path / "out.json"

    class _NotJsonable:
        pass

    with pytest.raises(TypeError):
        atomic_write_json(target, {"x": _NotJsonable()})
    assert _tmp_files(tmp_path) == []
    assert not target.exists()
