"""Ray White office sites share one listings API, reachable through each site's own proxy.

Every listing carries a numeric `price`, even when the advertised text is "Contact Agent";
that figure becomes `feed_price`. Status OFF means withdrawn or not publicly marketed: the
listing has no public page, but often still a full address, so it is reported as off-market.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from hunter.config import Source
from hunter.extract import Extractor
from hunter.models import Listing, ListingKind, PropertyType
from hunter.parsing import parse_price
from hunter.sources.web import Fetcher, FetchError

CATEGORIES = {
    "HSE": PropertyType.HOUSE, "UNT": PropertyType.UNIT, "APT": PropertyType.UNIT,
    "THS": PropertyType.TOWNHOUSE, "SDC": PropertyType.DUPLEX, "VIL": PropertyType.VILLA,
    "LAN": PropertyType.LAND,
}
PAGE = 100
OFF_MARKET_MAX_AGE = timedelta(days=120)  # older OFF records are usually withdrawn for good


def collect(source: Source, fetcher: Fetcher, extractor: Extractor) -> list[Listing]:
    base = source.list_urls[0].rstrip("/")
    org_ids = source.options.get("organisation_ids")
    if not org_ids:
        raise FetchError(f"{source.name}: options.organisation_ids is required")
    listings = [_listing(v, source, base, ListingKind.FOR_SALE) for v in _query(fetcher, base, org_ids, "CUR")]
    cutoff = datetime.now(timezone.utc) - OFF_MARKET_MAX_AGE
    for value in _query(fetcher, base, org_ids, "OFF"):
        if _when(value) >= cutoff:
            listings.append(_listing(value, source, base, ListingKind.OFF_MARKET))
    return listings


def _query(fetcher: Fetcher, base: str, org_ids: list[int], status: str) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    while True:
        # Rison-encoded query, the format the site's own JavaScript sends.
        q = (
            f"organisationId:!({','.join(map(str, org_ids))}),size:{PAGE},from:{len(values)},"
            f"statusCode:{status},typeCode:SAL,sort:!(%27creationTime%20desc%27)"
        )
        page = fetcher.get_json(f"{base}/api/proxy/v1/listings?q={q}")
        if not isinstance(page, dict) or "data" not in page:
            raise FetchError(f"unexpected Ray White API response: {str(page)[:200]}")
        batch = [item["value"] for item in page["data"]]
        values += batch
        if len(batch) < PAGE or len(values) >= page.get("hits", 0):
            return values


def _when(value: dict[str, Any]) -> datetime:
    stamp = value.get("updatedAt") or value.get("creationTime") or "1970-01-01T00:00:00+00:00"
    return datetime.fromisoformat(stamp)


def _listing(value: dict[str, Any], source: Source, base: str, kind: ListingKind) -> Listing:
    address = value.get("address") or {}
    street = " ".join(p for p in (address.get("streetNumber"), address.get("streetName"), address.get("streetType")) if p)
    if address.get("unitNumber") and street:
        street = f"{address['unitNumber']}/{street}"
    location = address.get("location") or {}
    land = next((m.get("value") for m in value.get("measurements", []) if m.get("code") == "LAS"), None)
    category = (value.get("categories") or [{}])[0].get("code")
    url = next((link["url"] for link in value.get("links", []) if link.get("code") == "PRL"), None)
    if kind == ListingKind.OFF_MARKET:
        url = None  # off-market listings have no public page (the short link 404s)
    elif url and urlparse(url).netloc != urlparse(base).netloc:
        url = None
    if value.get("underOffer"):
        kind = ListingKind.UNDER_OFFER
    price = parse_price(value.get("displayPrice"))
    feed_price = int(float(value["price"])) if str(value.get("price") or "").replace(".", "").isdigit() else None
    images = value.get("images") or []
    return Listing(
        source=source.name,
        ref=str(value["id"]) if value.get("id") else None,
        agency=source.agency,
        url=url,
        title=value.get("title") or value.get("heading"),
        address=street or None,
        suburb=address.get("suburb"),
        postcode=address.get("postCode"),
        property_type=CATEGORIES.get(category, PropertyType.OTHER if category else None),
        kind=kind,
        beds=value.get("bedrooms"),
        baths=value.get("bathrooms"),
        cars=value.get("carSpaces"),
        land_m2=land or None,
        price=price,
        feed_price=feed_price if feed_price and not price.is_known else None,
        lat=location.get("lat"),
        lng=location.get("lon"),
        photo_url=images[0].get("url") if images else None,
    )
