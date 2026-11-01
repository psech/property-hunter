"""Push Creative's CNS sites (The Agency, Century 21 Sutherland Shire) list every property for sale on
one page, as tiles carrying the address, rooms, land, status and price text.

Detail pages add only a description and coordinates, and Century 21's coordinates can be wrong (a
Heathcote listing placed in Victoria), so these listings are located by geocoding the address.
"""

from __future__ import annotations

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode

from hunter.config import Source
from hunter.extract import Extractor
from hunter.models import Listing, ListingKind, PropertyType
from hunter.parsing import parse_area_m2, parse_int, parse_kind, parse_price
from hunter.sources.web import Fetcher, FetchError, save_debug

TYPES = {
    "hou": PropertyType.HOUSE, "vil": PropertyType.VILLA, "dup": PropertyType.DUPLEX,
    "tow": PropertyType.TOWNHOUSE, "apt": PropertyType.UNIT, "unt": PropertyType.UNIT, "lan": PropertyType.LAND,
}


def collect(source: Source, fetcher: Fetcher, extractor: Extractor) -> list[Listing]:
    listings: list[Listing] = []
    for url in source.list_urls:
        html = fetcher.get(url, source.fetch)
        tiles = HTMLParser(html).css("li[data-propertyid]")
        if not tiles:
            save_debug(url, html)
            raise FetchError(f"no property tiles on {url}")
        listings += [_listing(tile, source) for tile in tiles]
    return listings


def _text(tile: LexborNode, selector: str) -> str | None:
    node = tile.css_first(selector)
    if node is None:
        return None
    return " ".join(node.text().replace("\xa0", " ").split()) or None


def _listing(tile: LexborNode, source: Source) -> Listing:
    card = tile.css_first(".propertyTile")
    code = card.attributes.get("data-property-type") if card else None
    contract = _text(tile, ".propertyTile-contracttext") or ""
    price_text = (_text(tile, ".propertyTile-pricetext") or "").strip(" |") or None  # often "| Contact Agent"
    if contract.lower() == "auction":
        price_text = f"Auction {price_text or ''}".strip()  # the price slot holds the auction date
    # The banner ("Under Offer") outranks the contract text; the price slot can say "SOLD BY <agent>".
    kind = parse_kind(_text(tile, ".propertyTile-banner"), contract) or ListingKind.FOR_SALE
    anchor = tile.css_first("a.propertyTile-anchor")
    image = tile.css_first(".propertyTile-image")
    return Listing(
        source=source.name,
        ref=tile.attributes.get("data-propertyid"),
        agency=source.agency,
        url=anchor.attributes.get("href") if anchor else None,
        address=_text(tile, ".propertyTile-address-streetaddress"),
        suburb=_text(tile, ".propertyTile-address-suburb"),
        property_type=TYPES.get(code or "", PropertyType.OTHER if code else None),
        kind=kind,
        beds=parse_int(_text(tile, ".propertyTile-icons-bed")),
        baths=parse_int(_text(tile, ".propertyTile-icons-bath")),
        cars=parse_int(_text(tile, ".propertyTile-icons-car")),
        land_m2=parse_area_m2(_text(tile, ".propertyTile-icons-area")),
        price=parse_price(price_text),
        photo_url=image.attributes.get("data-bg-src") if image else None,
    )
