import pytest

from hunter.models import ListingKind, PriceKind
from hunter.parsing import normalise_address, parse_kind, parse_price


@pytest.mark.parametrize(
    "text, kind, value, low, high",
    [
        ("$1,450,000", PriceKind.ASKING, 1_450_000, 1_450_000, 1_450_000),
        ("Offers over $1.4m", PriceKind.GUIDE, None, 1_400_000, 1_400_000),
        ("$1.2m - $1.3m", PriceKind.RANGE, None, 1_200_000, 1_300_000),
        ("Guide $1,350,000", PriceKind.GUIDE, None, 1_350_000, 1_350_000),
        ("Contact Agent", PriceKind.CONTACT_AGENT, None, None, None),
        ("Auction", PriceKind.AUCTION, None, None, None),
        ("Expressions of interest", PriceKind.CONTACT_AGENT, None, None, None),
        ("$950k", PriceKind.ASKING, 950_000, 950_000, 950_000),
    ],
)
def test_parse_price(text, kind, value, low, high):
    price = parse_price(text)
    assert (price.kind, price.value, price.low, price.high) == (kind, value, low, high)


def test_parse_price_ignores_small_amounts():
    assert parse_price("$5,000 deposit, contact agent").kind == PriceKind.CONTACT_AGENT


@pytest.mark.parametrize(
    "raw, suburb, expected",
    [
        ("12 Smith St, Kirrawee NSW 2232", None, "12 smith street kirrawee"),
        ("Unit 3, 12 Smith Street", "Kirrawee", "3/12 smith street kirrawee"),
        ("3 / 12 Smith St", "Kirrawee", "3/12 smith street kirrawee"),
        ("45 Oak Rd Kirrawee", "Kirrawee", "45 oak road kirrawee"),
    ],
)
def test_normalise_address(raw, suburb, expected):
    assert normalise_address(raw, suburb) == expected


@pytest.mark.parametrize(
    "label, kind",
    [
        ("Off Market", ListingKind.OFF_MARKET),
        ("Coming Soon", ListingKind.COMING_SOON),
        ("Under Contract", ListingKind.UNDER_OFFER),
        ("SOLD", ListingKind.SOLD),
        ("For Sale", ListingKind.FOR_SALE),
    ],
)
def test_parse_kind(label, kind):
    assert parse_kind(label) == kind
