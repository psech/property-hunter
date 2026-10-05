from pathlib import Path

from hunter.extract import from_jsonld, html_to_text
from hunter.models import ListingKind, PriceKind, PropertyType

FIXTURE = Path(__file__).parent / "fixtures" / "jsonld_listing.html"


def test_jsonld_listing():
    listing = from_jsonld(FIXTURE.read_text(), "test", "Test Agency", "https://agency.example/p/1")
    assert listing.address == "12 Smith Street, Kirrawee"
    assert listing.suburb == "Kirrawee"
    assert listing.beds == 4 and listing.baths == 2
    assert listing.price.kind == PriceKind.GUIDE and listing.price.low == 1_400_000
    assert listing.kind == ListingKind.OFF_MARKET
    assert listing.property_type == PropertyType.HOUSE
    assert (listing.lat, listing.lng) == (-34.04, 151.07)
    assert listing.photo_url == "https://agency.example/img/1.jpg"


def test_no_jsonld_returns_none():
    assert from_jsonld("<html><body>hi</body></html>", "t", "a", None) is None


def test_html_to_text_drops_chrome():
    text = html_to_text("<html><body><nav>Menu</nav><h1>Home</h1><p>4 bed</p><script>x()</script></body></html>")
    assert "Menu" not in text and "x()" not in text
    assert "# Home" in text and "4 bed" in text
