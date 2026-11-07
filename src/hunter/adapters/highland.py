"""Highland Property Group (ListOnce) lists its Shire offices' properties as cards, 16 to a page, with
the address, rooms and coordinates. Property type exists only as a search filter, so the pages are
read once per category; the price exists only on each listing's own page.

robots.txt asks for 10 s between requests, so detail pages are fetched only for listings in the
buyer's suburbs. Cards with the "Exclusive to Highland" banner are the agency's off-market listings:
they fill its off-market page.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode

from hunter.config import Source
from hunter.extract import Extractor
from hunter.models import Listing, ListingKind, PropertyType
from hunter.parsing import parse_int, parse_kind, parse_price
from hunter.sources.web import Fetcher, FetchError, save_debug

log = logging.getLogger(__name__)

CATEGORIES = {
    2: PropertyType.HOUSE, 3: PropertyType.UNIT, 5: PropertyType.TOWNHOUSE, 7: PropertyType.VILLA,
    19: PropertyType.DUPLEX, 1: PropertyType.LAND,
}
LISTING_ID = re.compile(r"/property/(\d+)/")


def collect(source: Source, fetcher: Fetcher, extractor: Extractor) -> list[Listing]:
    list_url = source.list_urls[0]
    listings: dict[str, Listing] = {}
    for category, property_type in CATEGORIES.items():
        for card in _pages(fetcher, f"{list_url}&category={category}"):
            listing = _listing(card, source, property_type)
            listings.setdefault(listing.url, listing)
    for card in _pages(fetcher, list_url):  # the few listings filed under no category
        listing = _listing(card, source, None)
        listings.setdefault(listing.url, listing)

    wanted = {suburb.lower() for suburb in source.buyer_suburbs}
    details = [listing for listing in listings.values() if (listing.suburb or "").lower() in wanted]
    for listing in details[: source.max_details]:
        try:
            _add_details(listing, fetcher.get(listing.url))
        except FetchError as exc:
            log.warning("%s: %s", source.name, exc)
    return list(listings.values())


def _pages(fetcher: Fetcher, url: str) -> list[LexborNode]:
    cards: list[LexborNode] = []
    while url:
        html = fetcher.get(url)
        tree = HTMLParser(html)
        page = tree.css("article.listing-card")
        if not page and not cards and "Properties Found" not in html:
            save_debug(url, html)
            raise FetchError(f"no listing cards on {url}")
        cards += page
        next_link = tree.css_first("a.next")
        url = urljoin(url, next_link.attributes["href"]) if next_link else None
    return cards


def _text(node: LexborNode, selector: str) -> str | None:
    found = node.css_first(selector)
    if found is None:
        return None
    return " ".join(found.text().split()) or None


def _listing(card: LexborNode, source: Source, property_type: PropertyType | None) -> Listing:
    url = card.css_first("a.listing-card__container").attributes["href"]
    counts = {
        group.css_first("img").attributes.get("alt"): parse_int(_text(group, ".listing-card__count"))
        for group in card.css(".listing-card__icon-group")
        if group.css_first("img")
    }
    image = card.css_first("img.listing-card__img")
    srcset = (image.attributes.get("srcset") or "") if image else ""
    match = LISTING_ID.search(url)
    return Listing(
        source=source.name,
        ref=match.group(1) if match else None,
        agency=source.agency,
        url=url,
        address=_text(card, ".listing-card__address"),
        suburb=_text(card, ".listing-card__suburb"),
        property_type=property_type,
        kind=ListingKind.OFF_MARKET if card.css_first(".listing-card__exclusive-banner") else ListingKind.FOR_SALE,
        beds=counts.get("Bedrooms") or None,  # land and commercial sites show 0
        baths=counts.get("Bathrooms") or None,
        cars=counts.get("Parking") or None,
        lat=_float(card.attributes.get("data-lat")),
        lng=_float(card.attributes.get("data-lng")),
        photo_url=srcset.split(" ")[0] or (image.attributes.get("src") if image else None),
    )


def _add_details(listing: Listing, html: str) -> None:
    price_text = _text(HTMLParser(html), "h2.listing-price")  # "For Sale - $1,150,000 - $1,200,000"
    listing.price = parse_price(price_text)
    if listing.kind == ListingKind.FOR_SALE:
        listing.kind = parse_kind(price_text) or ListingKind.FOR_SALE  # "Database Exclusive", "Under Offer"


def _float(value: str | None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
