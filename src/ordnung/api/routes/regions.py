"""The Land (Bundesland) the person or a sender is in, as the profile and a sender's page take it: one check for
both (SPEC § 21 "Holidays")."""

from __future__ import annotations

from ordnung.rules import normalize_region


def known_region(value: str | None) -> str | None:
    """``value`` as a Land's code (``NW``, ``BY`` …); ``None`` stays ``None`` (not known). ``ValueError`` for
    anything that is no German Bundesland."""
    if value is None:
        return None
    code = normalize_region(value)
    if code is None:
        raise ValueError(f"“{value}” is not a German Bundesland (use a code like NW or BY).")
    return code
