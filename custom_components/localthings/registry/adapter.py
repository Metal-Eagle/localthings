"""Adapter: BoundEntity list → flat state dict and command dispatch."""
from __future__ import annotations

from typing import Any

from .discovery import BoundEntity
from .subunits import SubUnit, canonical_view


def _key(b: BoundEntity) -> str:
    # b.sub_unit.key_prefix is '' for MAIN, so a device with no sub-units
    # (every device this integration shipped before issue #177) gets a
    # byte-identical key to before -- a hard regression guard, not a nicety
    # (see test_unique_ids.py and every golden file under tests/fixtures/golden/).
    return f"{b.sub_unit.key_prefix}{b.key_override or b.desc.key}{b.instance}"


def flatten(bound: list[BoundEntity], resources: dict) -> dict[str, Any]:
    """Map bound entities to their current scalar values.

    `exists_fn(rep, resources)` receives that entity's own sub-unit's
    *canonical* resources view (see subunits.canonical_view), not the raw
    actual-href snapshot -- an exists_fn that scans the whole resources dict
    for a sibling href (e.g. is_legacy_board) must judge each unit on its
    own resources, not see another unit's hrefs bleed in under the same
    canonical key. Views are built once per distinct sub-unit per call, not
    once per entity -- O(sub-units), not O(bound entities).
    """
    out: dict[str, Any] = {}
    # SubUnit is a frozen dataclass (hashable, equal by value), so it can key
    # `views` directly -- no need to re-derive an identity for it out of
    # (kind, key) first.
    all_units = list(dict.fromkeys(b.sub_unit for b in bound))
    views: dict[SubUnit, dict] = {}

    for b in bound:
        rep = resources.get(b.href) or {}
        if b.desc.exists_fn is not None:
            view = views.get(b.sub_unit)
            if view is None:
                view = canonical_view(b.sub_unit, resources, all_units)
                views[b.sub_unit] = view
            if not b.desc.exists_fn(rep, view):
                continue
        if b.desc.rep_fn is not None:
            out[_key(b)] = b.desc.rep_fn(rep)
        elif b.desc.field:
            out[_key(b)] = b.desc.value_fn(rep.get(b.desc.field))
    return out
