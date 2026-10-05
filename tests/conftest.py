from datetime import date

import pytest

from hunter.config import load_criteria, load_stations
from hunter.models import Enriched, GeoMetrics, Listing, ListingKind
from hunter.parsing import parse_price


@pytest.fixture
def criteria(monkeypatch):
    monkeypatch.setenv("BUDGET_MAX", "1500000")
    return load_criteria()


@pytest.fixture
def stations():
    return load_stations()


@pytest.fixture
def today():
    return date(2026, 10, 11)


def make(
    address="12 Smith St",
    suburb="Kirrawee",
    price="$1,400,000",
    kind=ListingKind.FOR_SALE,
    beds=4,
    walk_min=15.0,
    url="https://agency.example/listing/1",
    **listing_fields,
) -> Enriched:
    listing = Listing(
        source="test", agency="Test Agency", url=url, address=address, suburb=suburb,
        price=parse_price(price), kind=kind, beds=beds, **listing_fields,
    )
    geo = GeoMetrics(walk_min=walk_min, walk_km=walk_min / 12, drive_min=walk_min / 3, station="Kirrawee",
                     station_walk_min=8, stops_to_school=0, routed=True)
    return Enriched(listing=listing, geo=geo)
