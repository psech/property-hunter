"""Box+Dice franchise sites (One Agency) list an office's properties as cards: 15 on the page, the
rest 15 at a time from /ajax-listings, the way the site's "View More Listings" button asks for them.
Cards carry the suburb, street address, price text, rooms and an "Under Offer" badge; the property
category, land size and coordinates exist only on each listing's own page.

Cloudflare challenges a burst of about 20 requests, so detail pages are fetched only for listings in
the buyer's suburbs. (robots.txt forbids only AI training, so the LLM may read these pages; the
markup is regular enough not to need it.)
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode

from hunter.config import Source
from hunter.extract import Extractor
from hunter.models import Listing, ListingKind, PropertyType
from hunter.parsing import parse_area_m2, parse_int, parse_kind, parse_price, parse_property_type
from hunter.sources.web import Fetcher, FetchError, save_debug

log = logging.getLogger(__name__)

PAGE_SIZE = 15
MAX_PAGES = 20
LISTING_ID = re.compile(r"listing_id=(\d+)")
COORDINATES = re.compile(r"var listing = \{\s*lat: (-?[\d.]+),\s*lng: (-?[\d.]+)")


def collect(source: Source, fetcher: Fetcher, extractor: Extractor) -> list[Listing]:
    list_url = source.list_urls[0]
    html = fetcher.get(list_url)
    cards = HTMLParser(html).css("div.index-item")
    if not cards and not re.search(r"\b0 properties\b", html):
        save_debug(list_url, html)
        raise FetchError(f"no listing cards on {list_url}")

    batch = cards
    for page in range(1, MAX_PAGES):
        if len(batch) < PAGE_SIZE:
            break
        batch = HTMLParser(fetcher.get(_more_url(list_url, page * PAGE_SIZE))).css("div.index-item")
        cards += batch

    listings = {listing.url: listing for listing in (_listing(card, source, list_url) for card in cards)}
    wanted = {suburb.lower() for suburb in source.buyer_suburbs}
    details = [listing for listing in listings.values() if (listing.suburb or "").lower() in wanted]
    for listing in details[: source.max_details]:
        try:
            _add_details(listing, fetcher.get(listing.url))
        except FetchError as exc:
            log.warning("%s: %s", source.name, exc)
    return list(listings.values())


def _more_url(list_url: str, offset: int) -> str:
    """The next batch of cards: /listings?type=Buy&office_id=N -> /ajax-listings?offset_val=15&type=Buy&office_id=N."""
    parts = urlparse(list_url)
    return parts._replace(path="/ajax-listings", query=f"offset_val={offset}&{parts.query}").geturl()


def _text(node: LexborNode, selector: str) -> str | None:
    found = node.css_first(selector)
    if found is None:
        return None
    return " ".join(found.text().split()) or None


def _listing(card: LexborNode, source: Source, list_url: str) -> Listing:
    url = urljoin(list_url, card.css_first(".index-item-link a").attributes["href"])
    info = card.css_first(".index-item-info")
    price_text = (info.attributes.get("title") or info.text()).strip() if info else None
    counts = {
        icon.css_first("img").attributes.get("alt"): parse_int(icon.text())
        for icon in card.css(".footer-icon")
        if icon.css_first("img")
    }
    if card.css_first(".under-offer"):
        kind = ListingKind.UNDER_OFFER
    else:
        kind = parse_kind(price_text) or ListingKind.FOR_SALE  # "AUCTION UNLESS SOLD PRIOR", "CONTACT AGENT"
    image = card.css_first("img.index-preview-img")
    match = LISTING_ID.search(url)
    return Listing(
        source=source.name,
        ref=match.group(1) if match else None,
        agency=source.agency,
        url=url,
        address=_text(card, ".index-item-subheader"),
        suburb=_text(card, ".index-item-header"),
        kind=kind,
        price=parse_price(price_text),
        beds=counts.get("Bedrooms") or None,
        baths=counts.get("Bathrooms") or None,
        cars=counts.get("Parking") or None,
        photo_url=image.attributes.get("src") if image else None,
    )


def _add_details(listing: Listing, html: str) -> None:
    fields = {
        " ".join(label.text().split()): " ".join((label.parent.text(deep=False) or "").split())
        for label in HTMLParser(html).css(".listing-property-separator > strong")
    }
    if fields.get("Property Type") == "Commercial":  # category "Retail", "Offices"
        listing.property_type = PropertyType.OTHER
    else:
        listing.property_type = parse_property_type(fields.get("Property Category"))  # "House", "Apartment"
    listing.land_m2 = parse_area_m2(fields.get("Land Size"))  # "999.1 Sqm"
    if match := COORDINATES.search(html):
        listing.lat, listing.lng = float(match.group(1)), float(match.group(2))
