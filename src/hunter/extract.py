"""Turns fetched pages and emails into Listings: structured data first, the LLM only as a fallback."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from markdownify import markdownify
from pydantic import BaseModel
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from hunter.cache import JsonCache
from hunter.llm import Llm, LlmUnavailable
from hunter.models import Listing, ListingKind, PropertyType
from hunter.parsing import parse_int, parse_kind, parse_price, parse_property_type

log = logging.getLogger(__name__)

_LISTING_TYPES = {
    "realestatelisting", "residence", "house", "singlefamilyresidence", "apartment",
    "accommodation", "apartmentcomplex", "product", "offer", "place",
}


# ---------- JSON-LD ----------

def _ld_nodes(html: str) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for script in HTMLParser(html).css('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.text(strip=True))
        except json.JSONDecodeError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                nodes.append(node)
                stack.extend(v for k, v in node.items() if k in ("@graph", "itemOffered", "about", "mainEntity"))
    return nodes


def _types(node: dict[str, Any]) -> set[str]:
    raw = node.get("@type", [])
    return {t.lower() for t in ([raw] if isinstance(raw, str) else raw)}


def _first(*values: Any) -> Any:
    return next((v for v in values if v not in (None, "", [], {})), None)


def from_jsonld(html: str, source: str, agency: str, url: str | None) -> Listing | None:
    nodes = [n for n in _ld_nodes(html) if _types(n) & _LISTING_TYPES]
    if not nodes:
        return None
    merged: dict[str, Any] = {}
    for node in nodes:
        for key, value in node.items():
            merged.setdefault(key, value)

    address = merged.get("address") or {}
    if isinstance(address, str):
        street, locality, postcode = address, None, None
    else:
        street = address.get("streetAddress")
        locality = address.get("addressLocality")
        postcode = address.get("postalCode")
    geo = merged.get("geo") or {}
    offers = merged.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price_text = _first(
        offers.get("description"), offers.get("price") and f"${offers['price']}", merged.get("priceRange")
    )
    image = merged.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url")

    if not street and not locality:
        return None
    full_address = ", ".join(p for p in (street, locality) if p)
    name = merged.get("name")
    return Listing(
        source=source,
        agency=agency,
        url=merged.get("url") or url,
        title=name,
        address=full_address if street else None,
        suburb=locality,
        postcode=postcode,
        property_type=parse_property_type(" ".join(_types(merged)) + " " + (name or "")),
        kind=parse_kind(name, (merged.get("description") or "")[:300]) or ListingKind.FOR_SALE,
        beds=parse_int(_first(merged.get("numberOfBedrooms"), merged.get("numberOfRooms"))),
        baths=parse_int(_first(merged.get("numberOfBathroomsTotal"), merged.get("numberOfFullBathrooms"))),
        price=parse_price(price_text),
        lat=_float(geo.get("latitude")),
        lng=_float(geo.get("longitude")),
        photo_url=image,
        description=(merged.get("description") or "")[:2000] or None,
    )


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------- LLM fallback ----------

class LlmListing(BaseModel):
    title: str | None = None
    address: str | None = None
    suburb: str | None = None
    property_type: PropertyType | None = None
    kind: ListingKind | None = None
    beds: int | None = None
    baths: int | None = None
    cars: int | None = None
    land_m2: float | None = None
    price_text: str | None = None
    url: str | None = None
    photo_url: str | None = None
    summary: str | None = None


class LlmListings(BaseModel):
    listings: list[LlmListing]


_PROMPT = """You extract residential property listings for a buyer in the Sutherland Shire, NSW, Australia.
Return every distinct property for sale or about to be sold in the content below. Ignore rentals,
commercial property, agent profiles, and properties marked as already sold unless the content is
about the sale itself.

Rules:
- address: street address exactly as written (e.g. "3/12 Smith Street"); null if not given. Never invent one.
- suburb: the suburb name only.
- kind: off_market if described as off-market, silent, private or not publicly advertised;
  coming_soon if pre-market, coming soon or a sneak peek; exclusive if described as an exclusive
  listing; under_offer if under offer or contract; sold if sold; otherwise for_sale.{kind_hint}
- price_text: the price wording exactly as written (e.g. "Offers over $1.4m", "Contact agent"), or null.
- url: the link to the individual listing if present (absolute URL), else null.
- summary: one sentence on notable features, at most 25 words.

Source: {source}
Content:
\"\"\"
{content}
\"\"\"
"""


def html_to_text(html: str, max_chars: int = 30_000) -> str:
    tree = HTMLParser(html)
    for tag in tree.css("script, style, noscript, svg, header, footer, nav, form, iframe"):
        tag.decompose()
    body = tree.body.html if tree.body else html
    text = markdownify(body or "", strip=["img"], heading_style="ATX")
    lines = [line.rstrip() for line in text.splitlines()]
    compact = "\n".join(line for i, line in enumerate(lines) if line or (i and lines[i - 1]))
    return compact[:max_chars]


class Extractor:
    """Wraps the LLM path with a content-hash cache, so unchanged pages cost nothing."""

    def __init__(self, llm: Llm, cache: JsonCache):
        self.llm = llm
        self.cache = cache

    def with_llm(
        self,
        text: str,
        source: str,
        agency: str | None,
        url: str | None,
        kind_hint: ListingKind | None = None,
    ) -> list[Listing]:
        digest = hashlib.sha256(f"{source}\n{text}".encode()).hexdigest()[:24]
        cached = self.cache.get(digest)
        if cached is None:
            hint = f"\n- Every property in this content is {kind_hint.value} unless stated otherwise." if kind_hint else ""
            try:
                result = self.llm.structured(
                    _PROMPT.format(source=source, content=text, kind_hint=hint), LlmListings
                )
            except LlmUnavailable as exc:
                log.warning("Skipping LLM extraction for %s: %s", url or source, exc)
                return []
            cached = result.model_dump(mode="json")["listings"]
            self.cache.set(digest, cached)

        listings = []
        for raw in cached:
            item = LlmListing.model_validate(raw)
            if not item.address and not item.suburb and not item.title:
                continue
            listings.append(
                Listing(
                    source=source,
                    agency=agency,
                    url=item.url or url,
                    title=item.title,
                    address=item.address,
                    suburb=item.suburb,
                    property_type=item.property_type,
                    kind=item.kind or kind_hint or ListingKind.FOR_SALE,
                    beds=item.beds,
                    baths=item.baths,
                    cars=item.cars,
                    land_m2=item.land_m2,
                    price=parse_price(item.price_text),
                    photo_url=item.photo_url,
                    description=item.summary,
                )
            )
        return listings
