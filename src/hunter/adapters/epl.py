"""WordPress sites running Easy Property Listing (Rosalie Douglas) publish every sale listing through
the WordPress REST API as the `property` post type, with the plugin's fields under `meta`.

The site shows a street address only when `property_address_display` is "yes", and a price only
when `property_price_display` is "yes" (otherwise "POA"); both rules are kept. The hidden figure in
`property_price` becomes `feed_price`. Status `offmarket` means taken off the market, as at Pulse, so
it is reported as withdrawn along with `withdrawn`; sold and leased listings are skipped. Land area
in unit "square" is square metres: the descriptions confirm it. Coordinates come from geocoding.
"""

from __future__ import annotations

import html
from typing import Any

from hunter.config import Source
from hunter.extract import Extractor
from hunter.models import Listing, ListingKind
from hunter.parsing import parse_kind, parse_price, parse_property_type
from hunter.sources.web import Fetcher, FetchError

PAGE = 100
STATUSES = {"current": ListingKind.FOR_SALE, "offmarket": ListingKind.WITHDRAWN, "withdrawn": ListingKind.WITHDRAWN}
LAND_UNITS = {"square": 1, "squareMeter": 1, "hectare": 10_000, "acre": 4046.86}


def collect(source: Source, fetcher: Fetcher, extractor: Extractor) -> list[Listing]:
    base = source.list_urls[0].rstrip("/")
    posts: list[dict[str, Any]] = []
    for page in range(1, 21):
        batch = fetcher.get_json(f"{base}/wp-json/wp/v2/property", params={"per_page": PAGE, "page": page})
        if not isinstance(batch, list):
            raise FetchError(f"unexpected property API response: {str(batch)[:200]}")
        posts += batch
        if len(batch) < PAGE:  # asking past the last page is a 400
            break
    return [_listing(post, source) for post in posts if (post.get("meta") or {}).get("property_status") in STATUSES]


def _text(value: Any) -> str:
    return html.unescape(str(value or "")).strip()


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _listing(post: dict[str, Any], source: Source) -> Listing:
    meta = post["meta"]
    title = _text((post.get("title") or {}).get("rendered"))
    excerpt = _text((post.get("excerpt") or {}).get("rendered"))
    kind = STATUSES[meta["property_status"]]
    if kind == ListingKind.FOR_SALE and (meta.get("property_under_offer") == "yes" or parse_kind(excerpt) == ListingKind.UNDER_OFFER):
        kind = ListingKind.UNDER_OFFER  # "DEPOSIT TAKEN – OPEN HOMES CANCELLED" opens the description

    street = " ".join(p for p in (_text(meta.get("property_address_street_number")), _text(meta.get("property_address_street"))) if p)
    if street and meta.get("property_address_sub_number"):
        street = f"{_text(meta['property_address_sub_number'])}/{street}"
    shown = meta.get("property_address_display") == "yes"

    price = parse_price(_text(meta.get("property_price_view")) if meta.get("property_price_display") == "yes" else None)
    feed_price = _number(meta.get("property_price"))
    area = _number(meta.get("property_land_area"))
    factor = LAND_UNITS.get(meta.get("property_land_area_unit") or "square")
    cars = sum(n for n in (_number(meta.get("property_garage")), _number(meta.get("property_carport"))) if n)
    image = ((post.get("yoast_head_json") or {}).get("og_image") or [{}])[0].get("url")
    return Listing(
        source=source.name,
        ref=str(post["id"]),
        agency=source.agency,
        url=post.get("link"),
        title=title or None,
        address=(street.title() if street.isupper() else street) if shown and street else None,
        suburb=_text(meta.get("property_address_suburb")).title() or None,
        postcode=_text(meta.get("property_address_postal_code")) or None,
        property_type=parse_property_type(meta.get("property_category")),
        kind=kind,
        beds=int(n) if (n := _number(meta.get("property_bedrooms"))) is not None else None,
        baths=int(n) if (n := _number(meta.get("property_bathrooms"))) is not None else None,
        cars=int(cars) if cars else None,
        land_m2=area * factor if area and factor else None,
        price=price,
        feed_price=int(feed_price) if feed_price and not price.is_known else None,
        photo_url=image,
    )
