"""Per-file-type attachment routing.

The destination for an attachment (local model vs. external provider) is a
per-workspace map keyed by normalised file type, not the old single "route
attachments local" rule. This module owns the three mechanical pieces that map
needs, so the schema, the service and the request path all agree:

  - `normalise_key`  - one filename/extension -> the canonical map key.
  - `route_for_attachment` - the request-time decision, including the
    unrecognised-type default (external).
  - `effective_map` / `overrides_from_full` - merge and prune against the
    shipped `DEFAULT_ATTACHMENT_ROUTING`, so a workspace stores only its diffs.

The shipped defaults themselves live in app/config.py (DEFAULT_ATTACHMENT_ROUTING).
"""

from __future__ import annotations

import re

from app.config import DEFAULT_ATTACHMENT_ROUTING

ROUTE_LOCAL = "local"
ROUTE_EXTERNAL = "external"
# "auto" = let DejaQ's content-difficulty judge decide local vs. external per
# file (master's existing attachment behaviour). The dashboard labels it
# "Classified by difficulty".
ROUTE_AUTO = "auto"
ROUTES = frozenset({ROUTE_LOCAL, ROUTE_EXTERNAL, ROUTE_AUTO})

# The route for a type that is in NEITHER the defaults nor the workspace's
# overrides. Captain-confirmed: an unknown type is sent to the external
# provider rather than guessed at locally.
UNRECOGNISED_ROUTE = ROUTE_EXTERNAL

# Common spellings folded onto one canonical key so ".jpeg" and ".jpg" (etc.)
# share a single dashboard entry and one stored assignment.
_ALIASES = {"jpeg": "jpg", "tif": "tiff", "yml": "yaml", "htm": "html", "mdown": "md", "markdown": "md"}

# A map key is an extension-like token: lowercase letters/digits, 1-16 chars.
# Anything else (dots, slashes, spaces) is rejected at write time so the stored
# map cannot hold keys a filename extension could never match.
_KEY_RE = re.compile(r"^[a-z0-9]{1,16}$")


def normalise_key(raw: str) -> str:
    """Canonical map key for a raw extension or type token.

    Lowercases, strips a leading dot/whitespace, and folds known aliases.
    Raises ValueError if the result is not a valid key - callers writing the
    map surface that as a 422; callers reading a filename at request time
    should use `type_key_for` instead, which returns None rather than raising.
    """
    key = (raw or "").strip().lower().lstrip(".")
    key = _ALIASES.get(key, key)
    if not _KEY_RE.match(key):
        raise ValueError(
            f"invalid file type {raw!r}: use a bare extension like 'csv' or 'pdf' "
            "(lowercase letters and digits, no dot)"
        )
    return key


def type_key_for(*, filename: str | None, mime: str | None, is_image: bool) -> str | None:
    """The map key for an actual attachment, or None if undeterminable.

    Prefers the filename's extension (the only reliable signal for DOCX and
    other container formats whose MIME subtype is useless). Falls back to the
    MIME subtype, which is what an `input_image` carries since the Responses
    image part has no filename. None (no extension, no usable subtype) is
    treated as unrecognised by route_for_attachment -> external.
    """
    name = (filename or "").strip().lower()
    if "." in name:
        ext = name.rsplit(".", 1)[1]
        try:
            return normalise_key(ext)
        except ValueError:
            return None
    sub = (mime or "").split(";", 1)[0].strip().lower()
    if "/" in sub:
        sub = sub.rsplit("/", 1)[1].split("+", 1)[0]  # image/svg+xml -> svg
        if sub.startswith("x-"):
            sub = sub[2:]
        try:
            return normalise_key(sub)
        except ValueError:
            return None
    return None


def effective_map(overrides: dict[str, str] | None) -> dict[str, str]:
    """The map a request routes on: shipped defaults with the workspace's
    diffs layered on top."""
    return {**DEFAULT_ATTACHMENT_ROUTING, **(overrides or {})}


def route_for_attachment(
    effective: dict[str, str], *, filename: str | None, mime: str | None, is_image: bool
) -> str:
    """"local", "external" or "auto" for one attachment.

    An unrecognised type (no key, or a key in neither defaults nor overrides)
    routes external - see UNRECOGNISED_ROUTE.
    """
    key = type_key_for(filename=filename, mime=mime, is_image=is_image)
    if key is None:
        return UNRECOGNISED_ROUTE
    return effective.get(key, UNRECOGNISED_ROUTE)


def validate_full_map(submitted: dict) -> dict[str, str]:
    """Normalise + validate a full effective map from a client (the dashboard
    sends the whole map), returning it with canonical keys. Raises ValueError
    on a bad key or route so the router can 422."""
    if not isinstance(submitted, dict):
        raise ValueError("attachment_routing must be an object of {type: 'local'|'external'}")
    cleaned: dict[str, str] = {}
    for raw_key, raw_route in submitted.items():
        key = normalise_key(str(raw_key))
        route = str(raw_route).strip().lower()
        if route not in ROUTES:
            raise ValueError(f"attachment_routing['{key}']: route must be 'local' or 'external', got {raw_route!r}")
        cleaned[key] = route
    return cleaned


def overrides_from_full(full: dict[str, str]) -> dict[str, str]:
    """Prune a full effective map down to only its diffs from the shipped
    defaults, so a workspace stores the minimum. An entry equal to its shipped
    default is dropped (that type is "using the default" and will follow future
    changes to DEFAULT_ATTACHMENT_ROUTING); a custom type - one not in the
    defaults at all - is always kept."""
    return {k: v for k, v in full.items() if DEFAULT_ATTACHMENT_ROUTING.get(k) != v}


def demo() -> None:
    assert normalise_key(".JPEG") == "jpg"
    assert normalise_key("csv") == "csv"
    try:
        normalise_key("bad ext")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

    eff = effective_map({"csv": "local", "heic": "external"})
    # csv default external -> overridden local; pdf untouched default auto
    assert eff["csv"] == "local"
    assert eff["pdf"] == "auto"

    # request-time routing (shipped defaults)
    assert route_for_attachment(effective_map(None), filename="q3.csv", mime="text/csv", is_image=False) == "external"
    assert route_for_attachment(effective_map(None), filename="report.pdf", mime=None, is_image=False) == "auto"
    assert route_for_attachment(effective_map(None), filename=None, mime="image/png", is_image=True) == "local"
    # unrecognised extension -> external
    assert route_for_attachment(effective_map(None), filename="thing.xyz", mime=None, is_image=False) == "external"
    # no signal at all -> external
    assert route_for_attachment(effective_map(None), filename=None, mime="", is_image=False) == "external"

    assert validate_full_map({"log": "auto"}) == {"log": "auto"}
    try:
        validate_full_map({"csv": "sideways"})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

    # pruning: an entry equal to default drops, a real override and a custom type stay
    pruned = overrides_from_full(validate_full_map({"pdf": "auto", "csv": "external", "md": "external", "heic": "external", "flac": "external"}))
    assert "pdf" not in pruned  # equals default (auto)
    assert "csv" not in pruned  # equals default (external)
    assert pruned["md"] == "external"  # moved from default auto
    assert pruned["flac"] == "external"  # custom type
    print("attachment_routing demo ok")


if __name__ == "__main__":
    demo()
