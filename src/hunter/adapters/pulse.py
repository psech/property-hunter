"""Pulse Property Agents (WordPress + 'stepps' theme) serves every listing from one JSON endpoint.

Off-market ("Pre-Market") listings appear in the same feed with `isOffMarket: true` and a blank
address; the suburb survives in the slug. Their pages need a registered account.
"""

from __future__ import annotations

import re
from typing import Any

from hunter.config import Source
from hunter.extract import Extractor
from hunter.models import Listing, ListingKind
from hunter.parsing import parse_kind, parse_price, parse_property_type
from hunter.sources.web import Fetcher, FetchError

PAGE = 100
SLUG = re.compile(r"/(?:property|land)/[a-z-]+?-nsw-(?P<suburb>[a-z-]+)-\w+/?$")


def collect(source: Source, fetcher: Fetcher, extractor: Extractor) -> list[Listing]:
    base = source.list_urls[0].rstrip("/")
    results: list[dict[str, Any]] = []
    page = 1
    while True:
        data = fetcher.get_json(
            f"{base}/wp-json/api/listings/all",
            params={"paged": page, "limit": PAGE, "status": "current", "type": "property"},
        )
        if not isinstance(data, dict) or not data.get("success"):
            raise FetchError(f"unexpected Pulse API response: {str(data)[:200]}")
        batch = data.get("results") or []
        results += batch
        if len(batch) < PAGE or len(results) >= data.get("total", 0):
            break
        page += 1
    return [_listing(r, source, base) for r in results]


def _suburb(result: dict[str, Any]) -> str | None:
    if suburb := (result.get("address") or {}).get("suburb"):
        return suburb
    if match := SLUG.search(result.get("slug") or ""):
        return match.group("suburb").replace("-", " ").title()
    return None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _listing(result: dict[str, Any], source: Source, base: str) -> Listing:
    address = result.get("address") or {}
    coords = address.get("coordinates") or {}
    price_text = (result.get("price") or {}).get("value") or ""
    if result.get("isOffMarket"):
        kind = ListingKind.COMING_SOON if "coming soon" in price_text.lower() else ListingKind.OFF_MARKET
    else:
        kind = parse_kind(result.get("statusCaption"), price_text) or ListingKind.FOR_SALE
    land = (result.get("landDetails") or {}).get("value") or None
    slug = result.get("slug")
    return Listing(
        source=source.name,
        ref=result.get("uniqueID") or (str(result["ID"]) if result.get("ID") else None),
        agency=source.agency,
        url=result.get("link") or (f"{base}{slug}" if slug else None),
        title=result.get("heading"),
        address=address.get("streetAddress") or None,
        suburb=_suburb(result),
        postcode=address.get("postcode") or None,
        property_type=parse_property_type(result.get("categories")),
        kind=kind,
        beds=result.get("bedrooms"),
        baths=result.get("bathrooms"),
        cars=result.get("parkingSpaces"),
        land_m2=_float(land),
        price=parse_price(price_text),
        lat=_float(coords.get("lat")),
        lng=_float(coords.get("lng")),
        photo_url=(result.get("images") or {}).get("featured"),
    )
