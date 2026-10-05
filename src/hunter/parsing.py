"""Turns free-text prices, addresses and listing labels into structured values."""

from __future__ import annotations

import re

from hunter.models import ListingKind, Price, PriceKind, PropertyType

_AMOUNT = re.compile(r"\$\s*(\d+(?:[.,]\d+)*)\s*(k|m|mil|million)?\b", re.IGNORECASE)


def _to_int(number: str, suffix: str | None) -> int:
    suffix = (suffix or "").lower()
    if suffix in ("m", "mil", "million"):
        return round(float(number.replace(",", "")) * 1_000_000)
    if suffix == "k":
        return round(float(number.replace(",", "")) * 1_000)
    return int(float(number.replace(",", "")))


def parse_price(text: str | None) -> Price:
    if not text or not text.strip():
        return Price()
    clean = " ".join(text.split())
    lower = clean.lower()
    # Ignore sub-$10k figures such as weekly rent or deposit amounts.
    amounts = [a for a in (_to_int(n, s) for n, s in _AMOUNT.findall(clean)) if a >= 10_000]

    if len(amounts) >= 2:
        return Price(kind=PriceKind.RANGE, text=clean, min=min(amounts[:2]), max=max(amounts[:2]))
    if len(amounts) == 1:
        amount = amounts[0]
        if re.search(r"\b(offers? (over|above|from)|from|above|over|guide|expressions?|eoi)\b", lower):
            return Price(kind=PriceKind.GUIDE, text=clean, min=amount)
        if re.search(r"\b(under|below|up to)\b", lower):
            return Price(kind=PriceKind.GUIDE, text=clean, max=amount)
        return Price(kind=PriceKind.ASKING, text=clean, value=amount)
    if "auction" in lower:
        return Price(kind=PriceKind.AUCTION, text=clean)
    if re.search(r"contact|enquire|price on application|\bpoa\b|by negotiation|expressions", lower):
        return Price(kind=PriceKind.CONTACT_AGENT, text=clean)
    return Price(kind=PriceKind.UNKNOWN, text=clean)


def parse_kind(*labels: str | None) -> ListingKind | None:
    """Maps agency status labels ('Off Market', 'Under Contract', ...) to a ListingKind."""
    text = " ".join(label for label in labels if label).lower()
    if not text:
        return None
    if re.search(r"\bsold\b", text):
        return ListingKind.SOLD
    if re.search(r"under (offer|contract)|deposit taken", text):
        return ListingKind.UNDER_OFFER
    if re.search(r"off[- ]?market|silent sale|private sale", text):
        return ListingKind.OFF_MARKET
    if re.search(r"coming soon|pre[- ]?market|sneak peek|just about to", text):
        return ListingKind.COMING_SOON
    if re.search(r"exclusive", text):
        return ListingKind.EXCLUSIVE
    if re.search(r"for sale|auction|current|buy", text):
        return ListingKind.FOR_SALE
    return None


def parse_property_type(text: str | None) -> PropertyType | None:
    if not text:
        return None
    lower = text.lower()
    for words, kind in (
        (("townhouse", "town house", "terrace"), PropertyType.TOWNHOUSE),
        (("duplex", "semi"), PropertyType.DUPLEX),
        (("villa",), PropertyType.VILLA),
        (("unit", "apartment", "flat", "studio"), PropertyType.UNIT),
        (("land", "vacant"), PropertyType.LAND),
        (("house", "home", "residence", "cottage"), PropertyType.HOUSE),
    ):
        if any(w in lower for w in words):
            return kind
    return PropertyType.OTHER


_STREET_TYPES = {
    "st": "street", "rd": "road", "ave": "avenue", "av": "avenue", "pde": "parade",
    "cres": "crescent", "cr": "crescent", "pl": "place", "cl": "close", "dr": "drive",
    "hwy": "highway", "ct": "court", "tce": "terrace", "gr": "grove", "gve": "grove",
    "ln": "lane", "la": "lane", "cct": "circuit", "blvd": "boulevard", "wy": "way",
    "esp": "esplanade", "sq": "square", "pkwy": "parkway",
}


def normalise_address(address: str | None, suburb: str | None = None) -> str | None:
    """Canonical form for de-duplication: '3/12 smith street kirrawee'."""
    if not address:
        return None
    text = address.lower()
    if suburb and suburb.lower() not in text:
        text = f"{text} {suburb.lower()}"
    text = re.sub(r"\b(unit|apartment|apt|villa|townhouse|lot)\s+(\w+)\s*[,/]?\s*(?=\d)", r"\2/", text)
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"\b(nsw|new south wales|australia)\b", " ", text)
    text = re.sub(r"[^\w/\- ]", " ", text)
    text = re.sub(r"\b2\d{3}\b(?=[\s]*$)", " ", text)  # trailing NSW postcode
    words = [_STREET_TYPES.get(w, w) for w in text.split()]
    return " ".join(words) or None


def parse_int(text: str | int | float | None) -> int | None:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    match = re.search(r"\d+", str(text))
    return int(match.group()) if match else None


def parse_area_m2(text: str | float | None) -> float | None:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    match = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(m2|m²|sqm|sq m|square metres|ha|hectares?)?", str(text), re.I)
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    unit = (match.group(2) or "").lower()
    return value * 10_000 if unit.startswith("ha") or unit.startswith("hectare") else value
