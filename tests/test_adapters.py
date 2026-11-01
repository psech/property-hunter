import json
from pathlib import Path

from hunter.adapters import eview, pulse, pushcreative, raywhite
from hunter.config import Source
from hunter.models import ListingKind, PriceKind, PropertyType

FIXTURES = Path(__file__).parent / "fixtures"


class FakeFetcher:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    def get_json(self, url, params=None, headers=None):
        self.urls.append((url, params))
        self.headers = headers
        return self.responses.pop(0)

    def get(self, url, method="httpx"):
        self.urls.append((url, None))
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
    withdrawn_data = json.loads((FIXTURES / "pulse_offmarket.json").read_text())
    fetcher = FakeFetcher([data, withdrawn_data])
    source = Source(name="pulse", agency="Pulse", adapter="pulse", list_urls=["https://www.pulseproperty.com.au"])
    public, hidden, coming, withdrawn = pulse.collect(source, fetcher, None)

    assert public.address == "4/85-87 Jannali Avenue" and public.suburb == "Jannali"
    assert public.kind == ListingKind.FOR_SALE and public.price.min == 1_050_000
    assert public.property_type == PropertyType.VILLA and public.lat == -34.021774291992

    assert hidden.kind == ListingKind.OFF_MARKET and hidden.address is None
    assert hidden.suburb == "Gymea Bay"  # from the slug
    assert hidden.url == "https://www.pulseproperty.com.au/property/house-nsw-gymea-bay-1p11468/"
    assert hidden.property_type == PropertyType.HOUSE

    assert coming.kind == ListingKind.COMING_SOON and coming.property_type == PropertyType.DUPLEX

    # Pulse's "offmarket" status: taken off the market unsold, address usually kept
    assert [params["status"] for _, params in fetcher.urls] == ["current", "offmarket"]
    assert withdrawn.kind == ListingKind.WITHDRAWN and withdrawn.address == "3 Kendall Place"
    assert withdrawn.price.min == 1_800_000


def test_eview():
    data = json.loads((FIXTURES / "eview_api.json").read_text())
    fetcher = FakeFetcher([data["current"], data["offmarket"], data["comingsoon"]])
    source = Source(name="fw", agency="Fox & Wood", adapter="eview",
                    list_urls=["https://foxandwood.com.au"], options={"office_id": 1496})
    house, unit, coming = eview.collect(source, fetcher, None)

    assert [params["status"] for _, params in fetcher.urls] == ["current", "offmarket", "comingsoon"]
    assert fetcher.headers == {"PageFrom": "archive"}  # without it, every eview office in Australia
    # the Airport West listing belongs to another office and is dropped

    assert house.address == "36 Freya Street" and house.suburb == "Kareela" and house.postcode == "2232"
    assert house.property_type == PropertyType.HOUSE and house.kind == ListingKind.FOR_SALE
    assert house.price.kind == PriceKind.GUIDE and house.price.min == 1_500_000
    assert (house.beds, house.baths, house.cars, house.land_m2) == (4, 2, 2, 556)
    assert (house.lat, house.lng) == (-34.0155034, 151.0826795)
    assert house.ref == "L42843920" and house.url.startswith("https://foxandwood.com.au/property/")

    assert unit.kind == ListingKind.UNDER_OFFER and unit.property_type == PropertyType.UNIT
    assert unit.land_m2 is None  # reported as 0

    assert coming.kind == ListingKind.COMING_SOON and coming.address is None and coming.suburb == "Gymea Bay"
    assert coming.lat is None and coming.price.kind == PriceKind.CONTACT_AGENT


def test_pushcreative():
    fetcher = FakeFetcher([(FIXTURES / "pushcreative_list.html").read_text()])
    source = Source(name="ta", agency="The Agency", adapter="pushcreative",
                    list_urls=["https://theagency.com.au/properties-for-sale?office=250"])
    villa, duplex, sold, apartment, under_offer = pushcreative.collect(source, fetcher, None)

    assert villa.address == "3/93 Gannons Road" and villa.suburb == "Caringbah South"
    assert villa.property_type == PropertyType.VILLA and villa.kind == ListingKind.FOR_SALE
    assert (villa.beds, villa.baths, villa.cars) == (2, 1, 1) and villa.ref == "89659"
    assert villa.price.kind == PriceKind.AUCTION  # "Forthcoming Auction | Contact Agent"
    assert villa.url == "https://theagency.com.au/property-villa-nsw-caringbah-south-89659"
    assert villa.photo_url.startswith("https://theagency.edge.pushcreative.com.au/")

    assert duplex.property_type == PropertyType.DUPLEX
    assert duplex.price.kind == PriceKind.AUCTION and "14th November" in duplex.price.text

    assert sold.kind == ListingKind.SOLD and sold.land_m2 == 470

    assert apartment.property_type == PropertyType.UNIT
    assert (apartment.price.min, apartment.price.max) == (850_000, 880_000)

    # Century 21: the banner says Under Offer while the price slot says "SOLD BY STEWART & JOEL"
    assert under_offer.kind == ListingKind.UNDER_OFFER and under_offer.land_m2 == 790.1
