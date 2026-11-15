"""WordPress sites on the Houzez theme (Watkins) publish listings through the WordPress REST API as the
`properties` post type, but the feed holds only the title, link and taxonomy terms: status, type,
label and suburb. The sale status's numeric ID is looked up by name, then the feed is filtered by it.

Address, postcode, price, rooms and land area are only on each listing's page, in labelled rows
("Price:", "Bedrooms:"). Those pages are fetched for listings in the buyer's suburbs only.
Coordinates come from geocoding the address.
"""

from __future__ import annotations

import html
import logging
from typing import Any

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from hunter.config import Source
from hunter.extract import Extractor
from hunter.models import Listing, ListingKind
from hunter.parsing import parse_area_m2, parse_int, parse_kind, parse_price, parse_property_type
from hunter.sources.web import Fetcher, FetchError

log = logging.getLogger(__name__)

PAGE = 100
SALE_STATUS = "For Sale"


def collect(source: Source, fetcher: Fetcher, extractor: Extractor) -> list[Listing]:
    api = source.list_urls[0].rstrip("/") + "/wp-json/wp/v2"
    statuses = fetcher.get_json(f"{api}/status", params={"per_page": PAGE, "_fields": "id,name"})
    sale_ids = [str(s["id"]) for s in statuses if isinstance(s, dict) and html.unescape(s.get("name", "")) == SALE_STATUS] \
        if isinstance(statuses, list) else []
    if not sale_ids:
        raise FetchError(f"no {SALE_STATUS!r} status in {api}/status: {str(statuses)[:200]}")

    posts: list[dict[str, Any]] = []
    for page in range(1, 21):
        batch = fetcher.get_json(f"{api}/properties", params={
            "status": ",".join(sale_ids), "per_page": PAGE, "page": page,
            "_embed": "wp:term", "_fields": "id,link,title,_links,_embedded",
        })
        if not isinstance(batch, list):
            raise FetchError(f"unexpected properties API response: {str(batch)[:200]}")
        posts += batch
        if len(batch) < PAGE:  # asking past the last page is a 400
            break

    listings = [_listing(post, source) for post in posts]
    wanted = {suburb.lower() for suburb in source.buyer_suburbs}
    for listing in [listing for listing in listings if (listing.suburb or "").lower() in wanted][: source.max_details]:
        try:
            _add_details(listing, fetcher.get(listing.url))
        except FetchError as exc:
            log.warning("%s: %s", source.name, exc)
    return listings


def _terms(post: dict[str, Any], taxonomy: str) -> list[str]:
    groups = (post.get("_embedded") or {}).get("wp:term") or []
    return [html.unescape(t["name"]) for group in groups for t in group if t.get("taxonomy") == taxonomy]


def _listing(post: dict[str, Any], source: Source) -> Listing:
    title = html.unescape((post.get("title") or {}).get("rendered") or "").strip()
    labels = _terms(post, "property_label")  # "UNDER OFFER/CONTRACT", "Deposit Taken", "Auction", "New"
    kind = ListingKind.UNDER_OFFER if parse_kind(title, *labels) == ListingKind.UNDER_OFFER else ListingKind.FOR_SALE
    types = _terms(post, "property_type")
    suburbs = _terms(post, "property_city")
    return Listing(
        source=source.name,
        ref=str(post["id"]),
        agency=source.agency,
        url=post.get("link"),
        title=title or None,
        suburb=suburbs[0] if suburbs else None,
        property_type=parse_property_type(types[0]) if types else None,
        kind=kind,
        price=parse_price(None),
    )


def _add_details(listing: Listing, page: str) -> None:
    rows: dict[str, str] = {}
    for item in HTMLParser(page).css("#address li, #detail li"):
        label = item.css_first("strong")
        if label is not None:
            name = label.text(strip=True).rstrip(":")
            rows[name] = " ".join(item.text().split())[len(label.text(strip=True)):].strip()
    if rows.get("Address"):
        listing.address = rows["Address"]  # "201/674 Old Princes Hwy"
    listing.suburb = rows.get("Suburb") or listing.suburb
    listing.postcode = rows.get("Postcode") or listing.postcode
    if rows.get("Price"):
        listing.price = parse_price(rows["Price"])
    listing.beds = parse_int(rows.get("Bedrooms"))
    listing.baths = parse_int(rows.get("Bathrooms"))
    listing.cars = parse_int(rows.get("Parking") or rows.get("Garages"))
    if land := rows.get("Land Area") or rows.get("Land Size") or rows.get("Land"):
        listing.land_m2 = parse_area_m2(land)
    if rows.get("Property Type"):
        listing.property_type = parse_property_type(rows["Property Type"])
    if image := HTMLParser(page).css_first('meta[property="og:image"]'):
        listing.photo_url = image.attributes.get("content")
