"""Data shapes shared by every pipeline stage."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ListingKind(StrEnum):
    OFF_MARKET = "off_market"
    COMING_SOON = "coming_soon"
    EXCLUSIVE = "exclusive"
    FOR_SALE = "for_sale"
    UNDER_OFFER = "under_offer"
    SOLD = "sold"

    @property
    def is_off_market(self) -> bool:
        return self in (ListingKind.OFF_MARKET, ListingKind.COMING_SOON, ListingKind.EXCLUSIVE)


class PropertyType(StrEnum):
    HOUSE = "house"
    TOWNHOUSE = "townhouse"
    DUPLEX = "duplex"
    VILLA = "villa"
    UNIT = "unit"
    LAND = "land"
    OTHER = "other"


class PriceKind(StrEnum):
    ASKING = "asking"
    GUIDE = "guide"
    RANGE = "range"
    AUCTION = "auction"
    CONTACT_AGENT = "contact_agent"
    UNKNOWN = "unknown"


class Price(BaseModel):
    kind: PriceKind = PriceKind.UNKNOWN
    text: str | None = None
    value: int | None = None
    min: int | None = None
    max: int | None = None

    @property
    def is_known(self) -> bool:
        return self.value is not None or self.min is not None or self.max is not None

    @property
    def low(self) -> int | None:
        return self.value if self.value is not None else (self.min or self.max)

    @property
    def high(self) -> int | None:
        return self.value if self.value is not None else (self.max or self.min)

    @property
    def mid(self) -> int | None:
        if self.value is not None:
            return self.value
        if self.min is not None and self.max is not None:
            return (self.min + self.max) // 2
        return self.min or self.max


class Listing(BaseModel):
    """One property as extracted from a source, before enrichment."""

    source: str
    ref: str | None = None  # the source's own stable ID for the listing, when it has one
    agency: str | None = None
    url: str | None = None
    title: str | None = None
    address: str | None = None
    suburb: str | None = None
    postcode: str | None = None
    property_type: PropertyType | None = None
    kind: ListingKind = ListingKind.FOR_SALE
    beds: int | None = None
    baths: int | None = None
    cars: int | None = None
    land_m2: float | None = None
    price: Price = Field(default_factory=Price)
    feed_price: int | None = None  # a figure in the agency's data that isn't advertised
    lat: float | None = None
    lng: float | None = None
    photo_url: str | None = None
    description: str | None = None


class Estimate(BaseModel):
    low: int
    mid: int
    high: int
    confidence: float
    rationale: str


class GeoMetrics(BaseModel):
    lat: float | None = None
    lng: float | None = None
    approx: bool = False            # True when located by suburb centroid, not the address
    straight_km: float | None = None
    walk_km: float | None = None
    walk_min: float | None = None
    drive_min: float | None = None
    routed: bool = False            # False when walk/drive figures are heuristics, not routing
    station: str | None = None
    station_walk_min: float | None = None
    stops_to_school: int | None = None


class Enriched(BaseModel):
    listing: Listing
    geo: GeoMetrics = Field(default_factory=GeoMetrics)
    estimate: Estimate | None = None
