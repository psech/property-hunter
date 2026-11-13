"""Ray White office sites share one listings API, reachable through each site's own proxy.

Every listing carries a numeric `price`, even when the advertised text is "Contact Agent";
that figure becomes `feed_price`. Only current listings are read: since November 2026 the proxy
answers status OFF (withdrawn or not publicly marketed) with 400 "Query out of scope".
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from hunter.config import Source
from hunter.extract import Extractor
from hunter.models import Listing, ListingKind, PropertyType
from hunter.parsing import parse_kind, parse_price
from hunter.sources.web import Fetcher, FetchError

CATEGORIES = {
    "HSE": PropertyType.HOUSE, "UNT": PropertyType.UNIT, "APT": PropertyType.UNIT,
    "THS": PropertyType.TOWNHOUSE, "SDC": PropertyType.DUPLEX, "VIL": PropertyType.VILLA,
    "LAN": PropertyType.LAND,
}
PAGE = 100


def collect(source: Source, fetcher: Fetcher, extractor: Extractor) -> list[Listing]:
    base = source.list_urls[0].rstrip("/")
    org_ids = source.options.get("organisation_ids")
    if not org_ids:
        raise FetchError(f"{source.name}: options.organisation_ids is required")
    return [_listing(value, source, base) for value in _query(fetcher, base, org_ids, "CUR")]


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


def _listing(value: dict[str, Any], source: Source, base: str) -> Listing:
    address = value.get("address") or {}
    street = " ".join(p for p in (address.get("streetNumber"), address.get("streetName"), address.get("streetType")) if p)
    if address.get("unitNumber") and street:
        street = f"{address['unitNumber']}/{street}"
    location = address.get("location") or {}
    land = next((m.get("value") for m in value.get("measurements", []) if m.get("code") == "LAS"), None)
    category = (value.get("categories") or [{}])[0].get("code")
    url = next((link["url"] for link in value.get("links", []) if link.get("code") == "PRL"), None)
    if url and urlparse(url).netloc != urlparse(base).netloc:
        url = None
    kind = ListingKind.FOR_SALE
    if value.get("underOffer"):
        kind = ListingKind.UNDER_OFFER
    if parse_kind(value.get("displayPrice")) == ListingKind.SOLD:
        kind = ListingKind.SOLD  # status still CUR, but the advertised price says "Sold | Contact Agent"
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
