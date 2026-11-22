"""WordPress sites on Reapit's Agentpoint "realty" plugin (JRE Property, Harwood, MattBlak, The Property
Co.) render listing cards server-side, 18 to a page, paged by path (/page/2/). Past the last page some
sites serve the first page again, so paging stops at the first page with nothing new.

Two card layouts exist. Harwood, JRE and MattBlak give the suburb and street separately, with a
contract label ("For Sale", "Auction", "Off-Market Opportunity"). The Property Co. gives one address
line ("1/9 Dunkeld Close Burraneer NSW"), the property type and a sticker ("Just Listed"); its suburb
is matched against the buyer's suburbs, and the listing page settles it. Off-market and pre-market
listings sit among the rest, marked in the label or the price text ("Pre Market Exclusive").

Listing pages give the property type and coordinates (a Leaflet marker); they're fetched for the
buyer's suburbs only. No layout shows land area.
"""

from __future__ import annotations

import logging
import re

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode

from hunter.config import Source
from hunter.extract import Extractor
from hunter.models import Listing, ListingKind
from hunter.parsing import parse_int, parse_kind, parse_price, parse_property_type
from hunter.sources.web import Fetcher, FetchError, save_debug

log = logging.getLogger(__name__)

PAGE_SIZE = 18
MAX_PAGES = 20
MARKER = re.compile(r"L\.marker\(\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\]")
URL_TYPE = re.compile(r"/residential/([a-z-]+)/\d+/?$")  # Harwood and JRE: /sale/nsw/sutherland/<suburb>/residential/<type>/<id>
STREET_END = re.compile(
    r"^(?P<street>.*?\b(?:street|st|road|rd|avenue|ave|parade|pde|crescent|cres|place|pl|close|cl|drive|dr|lane|ln|"
    r"way|court|ct|circuit|cct|grove|gr|terrace|tce|highway|hwy|boulevarde|boulevard|esplanade|square|walk|row|"
    r"rise|mews|glen|chase|loop|kingsway))\s+(?P<suburb>[a-z][a-z' -]*)$",
    re.IGNORECASE,
)


def collect(source: Source, fetcher: Fetcher, extractor: Extractor) -> list[Listing]:
    list_url = source.list_urls[0].rstrip("/") + "/"  # e.g. https://www.jreproperty.com.au/buy/properties-for-sale/
    listings: dict[str, Listing] = {}
    for page in range(1, MAX_PAGES + 1):
        url = list_url if page == 1 else f"{list_url}page/{page}/"
        html = fetcher.get(url)
        cards = HTMLParser(html).css(".listing-item")
        if not cards and page == 1 and "properties found" not in html.lower():
            save_debug(url, html)
            raise FetchError(f"no listing cards on {url}")
        new = 0
        for card in cards:
            listing = _listing(card, source)
            if listing and listing.url not in listings:
                listings[listing.url] = listing
                new += 1
        if new == 0 or len(cards) < PAGE_SIZE:
            break

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


def _split_address(line: str, suburbs: list[str]) -> tuple[str | None, str | None]:
    """'1/9 Dunkeld Close Burraneer NSW' -> ('1/9 Dunkeld Close', 'Burraneer')."""
    line = re.sub(r",?\s+NSW(\s+\d{4})?$", "", line.strip(), flags=re.IGNORECASE)
    for suburb in sorted(suburbs, key=len, reverse=True):  # "Gymea Bay" before "Gymea"
        if line.lower().endswith(" " + suburb.lower()):
            return line[: -len(suburb)].rstrip(" ,"), suburb
    if match := STREET_END.match(line):
        return match.group("street"), match.group("suburb").title()
    if not re.search(r"\d", line):  # the street is withheld: "Woolooware NSW"
        return None, line.title()
    return line, None


def _listing(card: LexborNode, source: Source) -> Listing | None:
    link = card.css_first("a.img-container[href]") or card.css_first("a[href]")
    if link is None:
        return None
    url = link.attributes["href"]
    suburb = _text(card.css_first(".suburb"))
    address = _text(card.css_first(".address"))
    if suburb and address:  # Harwood, JRE, MattBlak; MattBlak repeats the suburb: "28 Greygum Place, Gymea Bay"
        address = re.sub(rf",?\s*{re.escape(suburb)}$", "", address, flags=re.IGNORECASE) or address
    elif address:  # The Property Co.
        address, suburb = _split_address(address, source.buyer_suburbs)

    labels = [_text(card.css_first(".contract__label")), _text(card.css_first(".sticker"))]
    price_text = _text(card.css_first(".price .value")) or _text(card.css_first(".price"))
    type_text = _text(card.css_first(".property-type .value"))
    if not type_text and (match := URL_TYPE.search(url)):
        type_text = match.group(1)
    image = card.css_first("img")
    return Listing(
        source=source.name,
        ref=url.rstrip("/").rsplit("/", 1)[-1],
        agency=source.agency,
        url=url,
        title=link.attributes.get("title") or _text(card.css_first(".listing-headline")),
        address=address,
        suburb=suburb,
        property_type=parse_property_type(type_text) if type_text else None,
        kind=parse_kind(*labels, price_text) or ListingKind.FOR_SALE,
        price=parse_price(price_text),
        beds=parse_int(_text(card.css_first("li.bedroom"))),
        baths=parse_int(_text(card.css_first("li.bathroom"))),
        cars=parse_int(_text(card.css_first("li.carspace"))),
        photo_url=image.attributes.get("src") if image is not None else None,
    )


def _add_details(listing: Listing, html: str) -> None:
    tree = HTMLParser(html)
    if street := _text(tree.css_first(".listing-address .property-address")):  # The Property Co.
        listing.address = street
        listing.suburb = _text(tree.css_first(".listing-address .property-suburb")) or listing.suburb
    type_text = _text(tree.css_first(".address-section .property-type"))  # Harwood, JRE, MattBlak
    for row in tree.css(".detail-information li"):  # The Property Co.
        if _text(row.css_first(".detail-label")) == "Property Type":
            type_text = _text(row.css_first(".detail-value"))
    if type_text:
        listing.property_type = parse_property_type(type_text)
    if match := MARKER.search(html):
        listing.lat, listing.lng = float(match.group(1)), float(match.group(2))
    if image := tree.css_first('meta[property="og:image"]'):
        listing.photo_url = image.attributes.get("content") or listing.photo_url
