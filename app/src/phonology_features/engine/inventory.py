"""The Inventory contract.

One source of truth for "is this inventory data valid". Everything that
loads, edits, or saves inventory data routes through this module:
engine, builder, tests. No other call site is allowed to construct an
``Inventory`` from raw fields -- only ``parse``, ``from_grid``, or
``load`` accept untrusted data, and each of those funnels through
``parse`` so the validation code path is singular.

Parse-don't-validate: ``parse`` either returns a fully-normalized
``Inventory`` whose invariants are guaranteed to hold for the life of
the value, or raises ``ValidationError`` carrying every problem it
found (not just the first). Downstream code never has to re-check.

The instance is structurally immutable: ``features`` is a tuple,
``segments`` is a ``MappingProxyType`` of ``MappingProxyType``. Holders
may store the value directly without a defensive copy because the
caller cannot mutate it after construction. "Edits" are done by
constructing a new ``Inventory``.

Writes go through ``write_atomic`` which uses a tmp file + ``os.replace``
so a crash mid-write never leaves a truncated JSON on disk.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from phonology_features._logging import get_logger

_log = get_logger(__name__)

VALID_VALUES: frozenset[str] = frozenset({"+", "-", "0"})

# Inventory file format version. Bumped when the on-disk shape changes
# in a way old readers cannot understand. Files written by this version
# always include ``schema_version`` at the top level. Files written by
# previous versions omitted the field; reads treat the absence as
# ``CURRENT_SCHEMA_VERSION`` so existing bundled and user inventories
# load without migration.
#
# When you add version 2: keep version 1 in ``SUPPORTED_SCHEMA_VERSIONS``
# until at least one release has shipped the migration path, then drop
# it. Reading an unsupported version raises ``ValidationError`` with a
# clear message rather than guessing.
CURRENT_SCHEMA_VERSION: int = 1
SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1})


class ValidationError(Exception):
    """Raised by ``Inventory.parse`` when the input is not a valid
    inventory. Carries every problem found (not just the first) so a
    GUI surface can show the full list at once.

    ``str(err)`` is the first issue -- useful for status bars.
    ``err.issues`` is the full tuple, in the order the parser found
    them (top-level shape first, then per-feature, then per-segment,
    then per-cell).
    """

    def __init__(self, issues: tuple[str, ...]):
        if not issues:
            issues = ("Invalid inventory (no issue detail)",)
        self.issues: tuple[str, ...] = issues
        super().__init__(issues[0])


@dataclass(frozen=True)
class Inventory:
    """A validated phonological inventory.

    Fields:
      - ``name``: human-readable display name; never empty
      - ``metadata``: arbitrary metadata mapping (read-only view)
      - ``features``: declared feature names, in their declared order;
        non-empty strings, unique
      - ``segments``: ``{symbol: {feature: value}}``; symbols are
        non-empty strings, feature keys are a subset of ``features``,
        values are in ``VALID_VALUES``. Inner maps are read-only views.

    Missing-feature semantics: a segment's bundle may omit a declared
    feature; readers should treat the omission as ``"0"``. The parser
    does NOT auto-fill the omission because round-tripping should not
    silently inflate the on-disk file.
    """

    name: str
    metadata: Mapping[str, Any]
    features: tuple[str, ...]
    segments: Mapping[str, Mapping[str, str]]

    @classmethod
    def parse(cls, raw: Any, *, source: str | None = None) -> "Inventory":
        """Validate raw (already-JSON-decoded) data into an Inventory.

        Collects every issue before raising so the caller can show them
        all. ``source`` is included in error messages when provided
        (typically a file path) to help disambiguate when the GUI is
        loading multiple inventories.
        """
        issues: list[str] = []
        prefix = f"{source}: " if source else ""

        if not isinstance(raw, dict):
            raise ValidationError(
                (
                    f"{prefix}top-level JSON value must be an object, "
                    f"got {type(raw).__name__}",
                )
            )

        # ----- schema version -----
        # Checked BEFORE per-field validation: if we can't read the
        # format, every subsequent issue is meaningless. Missing is
        # treated as version 1 so files written before this field was
        # introduced load without migration.
        if "schema_version" in raw:
            sv = raw["schema_version"]
            # bool is a subclass of int; reject it explicitly so True
            # / False can't sneak through as "schema_version 1".
            if isinstance(sv, bool) or not isinstance(sv, int):
                raise ValidationError(
                    (
                        f"{prefix}'schema_version' must be an integer, "
                        f"got {type(sv).__name__}",
                    )
                )
            if sv not in SUPPORTED_SCHEMA_VERSIONS:
                supported = ", ".join(
                    str(v) for v in sorted(SUPPORTED_SCHEMA_VERSIONS)
                )
                raise ValidationError(
                    (
                        f"{prefix}unsupported schema_version {sv}; "
                        f"this build reads version(s) {supported}",
                    )
                )

        # ----- features -----
        if "features" not in raw:
            issues.append(f"{prefix}missing required key 'features'")
            features_tuple: tuple[str, ...] = ()
            declared: set[str] = set()
        else:
            features_raw = raw["features"]
            features_tuple, declared = _validate_features(
                features_raw, issues, prefix
            )

        # ----- segments -----
        if "segments" not in raw:
            issues.append(f"{prefix}missing required key 'segments'")
            segments_view: Mapping[str, Mapping[str, str]] = MappingProxyType(
                {}
            )
        else:
            segments_raw = raw["segments"]
            segments_view = _validate_segments(
                segments_raw, declared, issues, prefix
            )

        if issues:
            raise ValidationError(tuple(issues))

        # Collect metadata from BOTH conventions: an explicit
        # ``metadata`` object (Hayes shape) AND any top-level extras
        # like ``name``/``version``/``notes`` that bundled files store
        # at the root (general_features shape). The explicit metadata
        # object wins on key collision so callers can override.
        metadata: dict[str, Any] = {}
        for key, value in raw.items():
            # ``schema_version`` lives at the top level for tooling
            # visibility; never duplicate it into metadata or it would
            # round-trip into two places on save.
            if key in ("features", "segments", "metadata", "schema_version"):
                continue
            metadata[key] = value
        explicit_metadata = raw.get("metadata")
        if isinstance(explicit_metadata, dict):
            metadata.update(explicit_metadata)
        name = metadata.get("name")
        if not isinstance(name, str) or not name.strip():
            name = "Untitled Inventory"
        # Ensure name round-trips even when the input had none.
        metadata.setdefault("name", name)

        return cls(
            name=name,
            metadata=MappingProxyType(metadata),
            features=features_tuple,
            segments=segments_view,
        )

    @classmethod
    def from_grid(
        cls,
        *,
        name: str,
        features: list[str],
        segments: dict[str, dict[str, str]],
    ) -> "Inventory":
        """Construct from builder grid state. Validates by funneling
        through ``parse`` so there is exactly one validation code path.
        ASCII-minus normalization (Unicode ``−`` -> ``-``) happens
        here because the grid stores the Unicode form for display."""
        normalized_segments: dict[str, dict[str, str]] = {}
        for seg, feats in segments.items():
            normalized: dict[str, str] = {}
            for f, v in feats.items():
                if v == "−":
                    v = "-"
                normalized[f] = v
            normalized_segments[seg] = normalized
        return cls.parse(
            {
                "metadata": {"name": name},
                "features": features,
                "segments": normalized_segments,
            }
        )

    @classmethod
    def load(cls, path: str) -> "Inventory":
        """Read and parse a JSON inventory file. Raises
        ``ValidationError`` (with ``source=path`` in messages) on any
        problem; the underlying ``OSError`` / ``JSONDecodeError`` is
        wrapped as a ValidationError so callers only need to handle
        one exception type."""
        basename = os.path.basename(path)
        _log.debug("inventory load start: %s", basename)
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError as e:
            _log.warning("inventory load failed: %s: file not found", basename)
            raise ValidationError((f"{path}: file not found",)) from e
        except json.JSONDecodeError as e:
            _log.warning(
                "inventory load failed: %s: invalid JSON (%s line %d)",
                basename,
                e.msg,
                e.lineno,
            )
            raise ValidationError(
                (f"{path}: invalid JSON ({e.msg} on line {e.lineno})",)
            ) from e
        except OSError as e:
            _log.warning("inventory load failed: %s: %s", basename, e)
            raise ValidationError((f"{path}: {e}",)) from e
        try:
            inv = cls.parse(raw, source=path)
        except ValidationError as e:
            _log.warning(
                "inventory validation failed: %s (%d issue%s)",
                basename,
                len(e.issues),
                "" if len(e.issues) == 1 else "s",
            )
            raise
        _log.info(
            "inventory loaded: %s (%d segments, %d features)",
            basename,
            len(inv.segments),
            len(inv.features),
        )
        return inv

    # ----- output -----
    def to_json_dict(self) -> dict[str, Any]:
        """Plain dict suitable for ``json.dump``. Inner views are
        unwrapped to dicts because ``json.dump`` doesn't know about
        ``MappingProxyType``. ``schema_version`` is the first key by
        convention -- tooling that inspects without parsing (jq, grep,
        future migrators) can find it without walking the whole file.
        """
        return {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "metadata": dict(self.metadata),
            "features": list(self.features),
            "segments": {
                seg: dict(feats) for seg, feats in self.segments.items()
            },
        }

    def write_atomic(self, path: str) -> None:
        """Crash-safe write: serialize to a sibling tmp file, then
        ``os.replace`` onto the target. An interrupted run leaves
        either the old file untouched or the new file fully written;
        never a half-written file. External file watchers see one
        atomic rename rather than a series of partial writes.
        """
        atomic_write_json(path, self.to_json_dict())

    # ----- convenience accessors used widely -----
    def feature_value(self, segment: str, feature: str) -> str:
        """Value of ``feature`` for ``segment``. Missing => ``'0'``.
        Raises ``KeyError`` for unknown segment / feature."""
        if segment not in self.segments:
            raise KeyError(f"Segment '{segment}' not in inventory")
        if feature not in self.features:
            raise KeyError(f"Feature '{feature}' not in inventory")
        return self.segments[segment].get(feature, "0")


def _validate_features(
    features_raw: Any, issues: list[str], prefix: str
) -> tuple[tuple[str, ...], set[str]]:
    """Returns (tuple of valid feature names, set of those names).
    Appends any issues to ``issues``."""
    if not isinstance(features_raw, list):
        issues.append(
            f"{prefix}'features' must be a list of strings, "
            f"got {type(features_raw).__name__}"
        )
        return (), set()

    valid: list[str] = []
    seen: set[str] = set()
    for i, f in enumerate(features_raw):
        if not isinstance(f, str):
            issues.append(
                f"{prefix}'features[{i}]' is not a string "
                f"(got {type(f).__name__}: {f!r})"
            )
            continue
        if not f.strip():
            issues.append(f"{prefix}'features[{i}]' is empty")
            continue
        if f in seen:
            issues.append(f"{prefix}'features' contains duplicate {f!r}")
            continue
        seen.add(f)
        valid.append(f)

    # Normalized-collision check: two distinct literal names that
    # collapse to the same canonical key (e.g. "DelRel" vs
    # "delayed_release") would later raise AliasCollisionError inside
    # ``engine.grouped_segments`` -- uncaught, that escapes
    # ``_load_path`` and can crash app startup via the last-inventory
    # restore. Reject at the parser boundary so the parser remains the
    # single source of truth for "is this inventory valid".
    # Lazy import: segment_grouper depends on lru_cache + collections
    # only, no cycle with this module.
    from phonology_features.engine.segment_grouper import _normalize_key

    by_canonical: dict[str, list[str]] = {}
    for f in valid:
        by_canonical.setdefault(_normalize_key(f), []).append(f)
    for canonical, originals in by_canonical.items():
        if len(originals) > 1:
            issues.append(
                f"{prefix}features {sorted(originals)} collide after "
                f"normalization to {canonical!r}; rename or remove one"
            )
    return tuple(valid), seen


def _validate_segments(
    segments_raw: Any,
    declared: set[str],
    issues: list[str],
    prefix: str,
) -> Mapping[str, Mapping[str, str]]:
    """Returns a read-only view of validated segments. Appends issues."""
    if not isinstance(segments_raw, dict):
        issues.append(
            f"{prefix}'segments' must be an object, "
            f"got {type(segments_raw).__name__}"
        )
        return MappingProxyType({})

    result: dict[str, Mapping[str, str]] = {}
    for seg_name, seg_feats in segments_raw.items():
        if not isinstance(seg_name, str) or not seg_name:
            issues.append(
                f"{prefix}segment key {seg_name!r} must be a non-empty string"
            )
            continue
        if not isinstance(seg_feats, dict):
            issues.append(
                f"{prefix}segment {seg_name!r}: bundle must be an object, "
                f"got {type(seg_feats).__name__}"
            )
            continue
        inner: dict[str, str] = {}
        for feat_name, feat_val in seg_feats.items():
            if not isinstance(feat_name, str) or not feat_name:
                issues.append(
                    f"{prefix}segment {seg_name!r}: feature key "
                    f"{feat_name!r} must be a non-empty string"
                )
                continue
            if declared and feat_name not in declared:
                issues.append(
                    f"{prefix}segment {seg_name!r}: feature "
                    f"{feat_name!r} is not declared in 'features'"
                )
                continue
            if not isinstance(feat_val, str):
                issues.append(
                    f"{prefix}segment {seg_name!r}.{feat_name!r}: value must "
                    f"be a string, got {type(feat_val).__name__} ({feat_val!r})"
                )
                continue
            if feat_val not in VALID_VALUES:
                issues.append(
                    f"{prefix}segment {seg_name!r}.{feat_name!r}: invalid "
                    f"value {feat_val!r} (expected one of "
                    f"{sorted(VALID_VALUES)})"
                )
                continue
            inner[feat_name] = feat_val
        result[seg_name] = MappingProxyType(inner)
    return MappingProxyType(result)


def atomic_write_json(path: str, data: Any) -> None:
    """Write JSON to ``path`` atomically.

    Writes to a sibling tmp file in the same directory (so the rename
    is a same-filesystem move), fsyncs, then ``os.replace``s. A crash
    or kill anywhere before the replace leaves the destination
    untouched; the rename itself is atomic on POSIX and Windows.

    File watchers see exactly one filesystem event for the destination
    (the rename), not a sequence of write-truncate-write events that
    would each trigger reload.
    """
    basename = os.path.basename(path)
    _log.debug("atomic write start: %s", basename)
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(
        prefix=".tmp_inv_", suffix=".json", dir=directory
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException as e:
        _log.error("atomic write failed: %s: %s", basename, e)
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    _log.info("atomic write complete: %s", basename)
