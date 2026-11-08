"""Rex Siteloft agency sites (KORE) list properties as cards, 12 to a page, with the address, price
text, rooms and land area. Off-market listings sit among the rest, with "Off Market Opportunity" in
the price slot. Property type exists only as a search filter, so the pages are read once per category
and once unfiltered for anything filed under none. Coordinates come from geocoding the address.

The order of the unfiltered pages shifts between requests, so a single pass can miss listings; the
category passes cover them. Some off-market listings appear twice in the unfiltered pages, the second
time under a vanity link such as /listings/private: those duplicates are skipped.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode

from hunter.config import Source
from hunter.extract import Extractor
from hunter.models import Listing, ListingKind, PropertyType
from hunter.parsing import parse_area_m2, parse_int, parse_kind, parse_price
from hunter.sources.web import Fetcher, FetchError, save_debug

PAGE_SIZE = 12
MAX_PAGES = 20
CATEGORIES = {
    "House": PropertyType.HOUSE, "Townhouse": PropertyType.TOWNHOUSE, "Terrace": PropertyType.TOWNHOUSE,
    "Villa": PropertyType.VILLA, "DuplexSemi-detached": PropertyType.DUPLEX, "Unit": PropertyType.UNIT,
    "Apartment": PropertyType.UNIT, "Studio": PropertyType.UNIT,
}
LISTING_LINK = re.compile(r"^/listings/(residential|land|commercial)_sale-(\w+)-")
ADDRESS = re.compile(r"^(?P<street>.+?),\s*(?P<suburb>[^,]+?),?\s+NSW\s+(?P<postcode>\d{4})$")


def collect(source: Source, fetcher: Fetcher, extractor: Extractor) -> list[Listing]:
    list_url = source.list_urls[0]  # .../listings/?saleOrRental=Sale&status=available_under_contract&sortby=...
    listings: dict[str, Listing] = {}
    for category, property_type in CATEGORIES.items():
        for card in _pages(fetcher, f"{list_url}&category={category}"):
            if listing := _listing(card, source, list_url, property_type):
                listings.setdefault(listing.url, listing)
    for card in _pages(fetcher, list_url):  # land ("Residential") and anything without a category
        if listing := _listing(card, source, list_url, None):
            listings.setdefault(listing.url, listing)
    if not listings:
        raise FetchError(f"no listing cards on {list_url}")
    return list(listings.values())


def _pages(fetcher: Fetcher, url: str) -> list[LexborNode]:
    cards: list[LexborNode] = []
    for page in range(1, MAX_PAGES + 1):
        html = fetcher.get(f"{url}&page={page}")
        batch = [_card(heading) for heading in HTMLParser(html).css('a[href^="/listings/"] > h4')]
        if not batch and 'name="sortby"' not in html:  # not even the search form: not a listings page
            save_debug(url, html)
            raise FetchError(f"unexpected page at {url}")
        cards += batch
        if len(batch) < PAGE_SIZE:
            break
    return cards


def _card(heading: LexborNode) -> LexborNode:
    """The card around a listing's address heading: the nearest ancestor that also holds its photo."""
    node = heading
    while node.parent is not None and not node.css_first('img[data-testid="shared-image-component"]'):
        node = node.parent
    return node


def _listing(card: LexborNode, source: Source, list_url: str, property_type: PropertyType | None) -> Listing | None:
    heading = card.css_first('a[href^="/listings/"] > h4')
    href = heading.parent.attributes["href"]
    link = LISTING_LINK.match(href)
    if not link:
        return None  # a vanity link duplicating a listing that is also on its proper URL
    if link.group(1) == "land":
        property_type = PropertyType.LAND
    elif link.group(1) == "commercial":
        property_type = PropertyType.OTHER

    title = " ".join(heading.text().split())  # "12 / 43-49 Railway Parade, Engadine NSW 2233"
    match = ADDRESS.match(title)
    street = re.sub(r"\s*/\s*", "/", match.group("street")) if match else title
    labels = [" ".join(label.text().split()) for label in card.css("strong")]
    price_text = labels[0] if labels else None  # "Guide $1,450,000", "Off Market Opportunity"
    stats = [" ".join(p.text().split()) for p in card.css("p")]  # "4 Bed", "2 Bath", "2 Car", "354 m²"
    image = card.css_first('img[data-testid="shared-image-component"]')
    photo = image.attributes.get("src") if image else None
    return Listing(
        source=source.name,
        ref=link.group(2),
        agency=source.agency,
        url=urljoin(list_url, href),
        address=street,
        suburb=match.group("suburb") if match else None,
        postcode=match.group("postcode") if match else None,
        property_type=property_type,
        kind=parse_kind(*labels) or ListingKind.FOR_SALE,
        price=parse_price(price_text),
        beds=_stat(stats, "Bed"),
        baths=_stat(stats, "Bath"),
        cars=_stat(stats, "Car"),
        land_m2=next((parse_area_m2(s) for s in stats if s.endswith("m²")), None),
        photo_url=urljoin("https:", photo) if photo else None,
    )


def _stat(stats: list[str], unit: str) -> int | None:
    return next((parse_int(s) for s in stats if s.endswith(f" {unit}")), None)
