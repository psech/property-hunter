"""Sanders Property Agents list properties as cards, 20 to a search page, with the suburb, street,
rooms and price text ("For Sale: $925,000", "... Under Contract"). A page past the last one is empty.

Property type, land area, postcode and coordinates are only on each listing's own page, so those are
fetched for listings in the buyer's suburbs only. Off-market listings need a registered account and
aren't read.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode

from hunter.config import Source
from hunter.extract import Extractor
from hunter.models import Listing, ListingKind
from hunter.parsing import parse_area_m2, parse_int, parse_kind, parse_price, parse_property_type
from hunter.sources.web import Fetcher, FetchError, save_debug

log = logging.getLogger(__name__)

MAX_PAGES = 20
PHOTO = re.compile(r"url\(([^)]+)\)")


def collect(source: Source, fetcher: Fetcher, extractor: Extractor) -> list[Listing]:
    list_url = source.list_urls[0]  # .../search/buy/-/-/-/0/0?pg=1&sort=&agent=
    listings: dict[str, Listing] = {}
    for page in range(1, MAX_PAGES + 1):
        url = re.sub(r"([?&]pg=)\d+", rf"\g<1>{page}", list_url)
        html = fetcher.get(url)
        cards = HTMLParser(html).css(".listing-box")
        if not cards:
            if page == 1:
                save_debug(url, html)
                raise FetchError(f"no listing cards on {url}")
            break
        for card in cards:
            if listing := _listing(card, source, list_url):
                listings.setdefault(listing.url, listing)

    wanted = {suburb.lower() for suburb in source.buyer_suburbs}
    details = [listing for listing in listings.values() if (listing.suburb or "").lower() in wanted]
    for listing in details[: source.max_details]:
        try:
            _add_details(listing, fetcher.get(listing.url))
        except FetchError as exc:
            log.warning("%s: %s", source.name, exc)
    return list(listings.values())


def _text(node: LexborNode | None) -> str | None:
    if node is None:
        return None
    return " ".join(node.text().split()) or None


def _listing(card: LexborNode, source: Source, list_url: str) -> Listing | None:
    link = card.css_first("a[href]")
    if not link:
        return None
    price_text = _text(card.css_first(".listing-box--price"))
    stats = {_text(item.css_first(".feature-list-label")): _text(item.css_first(".feature-list--amount"))
             for item in card.css(".feature-list-item")}
    background = card.css_first(".panel-bg-image")
    photo = PHOTO.search(background.attributes.get("style") or "") if background is not None else None
    href = link.attributes["href"]
    return Listing(
        source=source.name,
        ref=href.strip("/"),  # "1P11236"
        agency=source.agency,
        url=urljoin(list_url, href.rstrip("/") + "/"),  # the bare /1P11236 redirects here
        address=_text(card.css_first(".listing-box--subtitle")),
        suburb=_text(card.css_first(".listing-box--title")),
        kind=parse_kind(price_text) or ListingKind.FOR_SALE,
        price=parse_price(price_text),
        beds=parse_int(stats.get("Bed")),
        baths=parse_int(stats.get("Bath")),
        cars=parse_int(stats.get("Car")),
        photo_url=photo.group(1) if photo else None,
    )


def _add_details(listing: Listing, html: str) -> None:
    tree = HTMLParser(html)
    facts = {_text(item.css_first(".inline-list--label")): _text(item.css_first(".inline-list--text"))
             for item in tree.css(".inline-list li")}
    if facts.get("Property Type"):
        listing.property_type = parse_property_type(facts["Property Type"])
    if facts.get("Land size"):
        listing.land_m2 = parse_area_m2(facts["Land size"])  # "1018 sqm"
    if postcode := tree.css_first('meta[property$="postal-code"], meta[name$="postal-code"]'):
        listing.postcode = postcode.attributes.get("content")
    if (map_ := tree.css_first("[data-lat][data-long]")) is not None:
        try:
            listing.lat = float(map_.attributes["data-lat"])
            listing.lng = float(map_.attributes["data-long"])
        except (TypeError, ValueError):
            pass
    if image := tree.css_first('meta[property="og:image"]'):
        listing.photo_url = image.attributes.get("content") or listing.photo_url
