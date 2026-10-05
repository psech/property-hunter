import json
from pathlib import Path

from hunter.adapters import pulse, raywhite
from hunter.config import Source
from hunter.models import ListingKind, PriceKind, PropertyType

FIXTURES = Path(__file__).parent / "fixtures"


class FakeFetcher:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    def get_json(self, url, params=None):
        self.urls.append((url, params))
        return self.responses.pop(0)


def test_raywhite():
    data = json.loads((FIXTURES / "raywhite_api.json").read_text())
    fetcher = FakeFetcher([data["current"], data["off"]])
    source = Source(name="rw", agency="Ray White", adapter="raywhite",
                    list_urls=["https://raywhitesutherlandshire.com.au"], options={"organisation_ids": [1, 2]})
    listings = raywhite.collect(source, fetcher, None)

    assert "organisationId:!(1,2)" in fetcher.urls[0][0] and "statusCode:CUR" in fetcher.urls[0][0]
    unit, contact, off = listings
    assert unit.address == "2/26-30 Harrow Road" and unit.suburb == "Sylvania"
    assert unit.property_type == PropertyType.UNIT and unit.price.kind == PriceKind.GUIDE
    assert unit.feed_price is None  # advertised price wins
    assert (unit.lat, unit.lng, unit.land_m2) == (-34.01, 151.1, None)
    assert unit.url == "https://raywhitesutherlandshire.com.au/L1"

    assert contact.kind == ListingKind.UNDER_OFFER
    assert contact.price.kind == PriceKind.CONTACT_AGENT and contact.feed_price == 1_600_000
    assert contact.land_m2 == 556

    assert off.kind == ListingKind.OFF_MARKET and off.url is None and off.address == "8 Barratta Place"
    # the stale OFF record (2025) is dropped


def test_pulse():
    data = json.loads((FIXTURES / "pulse_api.json").read_text())
    fetcher = FakeFetcher([data])
    source = Source(name="pulse", agency="Pulse", adapter="pulse", list_urls=["https://www.pulseproperty.com.au"])
    public, hidden, coming = pulse.collect(source, fetcher, None)

    assert public.address == "4/85-87 Jannali Avenue" and public.suburb == "Jannali"
    assert public.kind == ListingKind.FOR_SALE and public.price.min == 1_050_000
    assert public.property_type == PropertyType.VILLA and public.lat == -34.021774291992

    assert hidden.kind == ListingKind.OFF_MARKET and hidden.address is None
    assert hidden.suburb == "Gymea Bay"  # from the slug
    assert hidden.url == "https://www.pulseproperty.com.au/property/house-nsw-gymea-bay-1p11468/"
    assert hidden.property_type == PropertyType.HOUSE

    assert coming.kind == ListingKind.COMING_SOON and coming.property_type == PropertyType.DUPLEX
