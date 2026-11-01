"""Per-site adapters. Each turns a configured Source into Listings."""

from __future__ import annotations

from typing import Callable

from hunter.config import Source
from hunter.extract import Extractor
from hunter.models import Listing
from hunter.sources.web import Fetcher

Adapter = Callable[[Source, Fetcher, Extractor], list[Listing]]


def get_adapter(name: str) -> Adapter:
    from hunter.adapters import eview, generic, pulse, pushcreative, raywhite

    adapters: dict[str, Adapter] = {
        "eview": eview.collect,
        "generic": generic.collect,
        "pulse": pulse.collect,
        "pushcreative": pushcreative.collect,
        "raywhite": raywhite.collect,
    }
    if name not in adapters:
        raise KeyError(f"Unknown adapter {name!r}; known: {', '.join(sorted(adapters))}")
    return adapters[name]
