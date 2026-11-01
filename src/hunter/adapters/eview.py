"""eview group offices (Fox & Wood) run Pulse's stepps listings endpoint, with eview's field names.

Without the `PageFrom: archive` header the endpoint returns every eview office in Australia; with
it, only the site's own office. Live off-market listings are flagged in `current`; coming-soon ones
have a status of their own, and `offmarket` holds withdrawn listings, as at Pulse.
"""

from __future__ import annotations

import re
from typing import Any

from hunter.adapters.pulse import feed
from hunter.config import Source
from hunter.extract import Extractor
from hunter.models import Listing, ListingKind
from hunter.parsing import parse_kind, parse_price, parse_property_type
from hunter.sources.web import Fetcher

HEADERS = {"PageFrom": "archive"}
STATUSES = {"current": None, "offmarket": ListingKind.WITHDRAWN, "comingsoon": ListingKind.COMING_SOON}
STREET = re.compile(r"^(?:lot\s+)?\S*\d", re.IGNORECASE)  # titles of hidden-address listings are prose


def collect(source: Source, fetcher: Fetcher, extractor: Extractor) -> list[Listing]:
    base = source.list_urls[0].rstrip("/")
    office = source.options.get("office_id")
    listings = []
    for status, kind in STATUSES.items():
        for result in feed(fetcher, base, status, HEADERS):
            if office is None or str(result.get("officeID")) == str(office):
                listings.append(_listing(result, source, kind))
    return listings


def _coords(text: Any) -> tuple[float | None, float | None]:
    try:
        lat, lng = (float(part) for part in str(text).split(","))
        return lat, lng
    except ValueError:
        return None, None


def _listing(result: dict[str, Any], source: Source, kind: ListingKind | None) -> Listing:
    address = result.get("address") or {}
    price_text = (result.get("propertyPricing") or {}).get("value") or ""
    if kind is None:
        if result.get("isOffMarket"):
            kind = ListingKind.OFF_MARKET
        elif result.get("isComingSoon"):
            kind = ListingKind.COMING_SOON
        else:
            kind = parse_kind(price_text) or ListingKind.FOR_SALE
    title = (result.get("title") or "").strip()
    lat, lng = _coords(result.get("propertyCoords"))
    return Listing(
        source=source.name,
        ref=result.get("uniqueID") or (str(result["id"]) if result.get("id") else None),
        agency=source.agency,
        url=result.get("link"),
        title=result.get("propertyHeading") or title or None,
        address=title if STREET.match(title) else None,
        suburb=address.get("suburb") or None,
        postcode=address.get("postcode") or None,
        property_type=parse_property_type(result.get("propertyCategory")),
        kind=kind,
        beds=result.get("propertyBed"),
        baths=result.get("propertyBath"),
        cars=result.get("propertyParking"),
        land_m2=result.get("landArea") or None,
        price=parse_price(price_text),
        lat=lat,
        lng=lng,
        photo_url=result.get("propertyImage"),
    )
