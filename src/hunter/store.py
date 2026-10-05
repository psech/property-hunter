"""Memory: what has been seen, what has been sent, and what changed since then."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from hunter.models import Enriched
from hunter.parsing import normalise_address

# Fields whose change is worth telling the buyer about.
MATERIAL_FIELDS = ("price", "kind", "address", "beds", "baths", "land_m2")


def listing_key(item: Enriched) -> str:
    listing = item.listing
    if address := normalise_address(listing.address, listing.suburb):
        return f"addr:{address}"
    if listing.ref:
        return f"ref:{listing.source}:{listing.ref}"
    return f"url:{listing.url or ''}#{(listing.title or '').strip().lower()}"


def observation(item: Enriched) -> dict[str, Any]:
    listing = item.listing
    return {
        "price": listing.price.text or None,
        "price_low": listing.price.low,
        "kind": listing.kind.value,
        "address": listing.address,
        "beds": listing.beds,
        "baths": listing.baths,
        "land_m2": listing.land_m2,
    }


def fingerprint(obs: dict[str, Any]) -> str:
    material = {
        "price": obs.get("price_low") or (obs.get("price") or "").lower(),
        **{k: obs.get(k) for k in MATERIAL_FIELDS if k != "price"},
    }
    return hashlib.sha1(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()[:16]


def describe_changes(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    labels = {"price": "price", "kind": "status", "address": "address", "beds": "beds", "baths": "baths", "land_m2": "land"}
    changes = []
    for name in MATERIAL_FIELDS:
        old, new = before.get(name), after.get(name)
        if name == "price" and before.get("price_low") == after.get("price_low") and old and new:
            continue  # same number, reworded
        if old != new:
            pretty = lambda v: "—" if v in (None, "") else str(v).replace("_", "-")
            changes.append(f"{labels[name]} {pretty(old)} → {pretty(new)}")
    return changes


@dataclass
class Change:
    key: str
    item: Enriched
    status: str  # "new" | "changed"
    details: list[str] = field(default_factory=list)


class Store:
    def __init__(self, path: Path):
        self.path = path
        data = json.loads(path.read_text()) if path.exists() else {}
        self.meta: dict[str, Any] = data.get("meta", {})
        self.listings: dict[str, dict[str, Any]] = data.get("listings", {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "meta": self.meta, "listings": dict(sorted(self.listings.items()))}
        self.path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")

    def _find(self, key: str, item: Enriched) -> str | None:
        if key in self.listings:
            return key
        listing = item.listing
        ref = f"{listing.source}:{listing.ref}" if listing.ref else None
        if key.startswith("addr:") and (ref or listing.url):
            # The address may have been revealed since we last saw this listing without one.
            for old_key, record in self.listings.items():
                if old_key.startswith("addr:"):
                    continue
                if (ref and record.get("ref") == ref) or (listing.url and record.get("url") == listing.url):
                    self.listings[key] = self.listings.pop(old_key)
                    self.listings[key]["key"] = key
                    return key
        return None

    def observe(self, item: Enriched, today: date) -> tuple[str, dict[str, Any]]:
        """Records a sighting and returns (key, record)."""
        key = listing_key(item)
        found = self._find(key, item)
        obs = observation(item)
        stamp = today.isoformat()
        if found is None:
            record = {
                "key": key,
                "first_seen": stamp,
                "history": [],
                "last_notified_hash": None,
                "last_notified_at": None,
                "last_notified_observation": None,
            }
            self.listings[key] = record
        else:
            record = self.listings[found]
        record.update(
            source=item.listing.source,
            ref=f"{item.listing.source}:{item.listing.ref}" if item.listing.ref else None,
            agency=item.listing.agency,
            url=item.listing.url,
            suburb=item.listing.suburb,
            last_seen=stamp,
            active=True,
            last_observation=obs,
            geo=item.geo.model_dump(exclude_none=True),
        )
        history = record["history"]
        entry = {"date": stamp, "price": obs["price"], "kind": obs["kind"]}
        if not history or {k: history[-1].get(k) for k in ("price", "kind")} != {k: entry[k] for k in ("price", "kind")}:
            history.append(entry)
        return key, record

    def pending_change(self, key: str, item: Enriched) -> Change | None:
        """A notification-worthy change for an observed listing, or None if the buyer already knows."""
        record = self.listings[key]
        obs = record["last_observation"]
        if record.get("last_notified_hash") is None:
            return Change(key=key, item=item, status="new")
        if fingerprint(obs) == record["last_notified_hash"]:
            return None
        return Change(key=key, item=item, status="changed", details=describe_changes(record["last_notified_observation"] or {}, obs))

    def mark_notified(self, key: str, today: date) -> None:
        record = self.listings[key]
        record["last_notified_hash"] = fingerprint(record["last_observation"])
        record["last_notified_observation"] = record["last_observation"]
        record["last_notified_at"] = today.isoformat()

    def mark_missing(self, seen_keys: set[str], healthy_sources: set[str]) -> int:
        """Marks listings inactive when their source ran fine but no longer shows them."""
        count = 0
        for key, record in self.listings.items():
            if key not in seen_keys and record.get("source") in healthy_sources and record.get("active"):
                record["active"] = False
                count += 1
        return count
