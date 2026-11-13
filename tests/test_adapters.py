import json
from pathlib import Path

from hunter.adapters import boxdice, eview, highland, pulse, pushcreative, raywhite, rex
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
    fetcher = FakeFetcher([data["current"]])
    source = Source(name="rw", agency="Ray White", adapter="raywhite",
                    list_urls=["https://raywhitesutherlandshire.com.au"], options={"organisation_ids": [1, 2]})
    listings = raywhite.collect(source, fetcher, None)

    assert "organisationId:!(1,2)" in fetcher.urls[0][0] and "statusCode:CUR" in fetcher.urls[0][0]
    unit, contact = listings
    assert len(fetcher.urls) == 1  # status OFF is no longer queried: the proxy refuses it
    assert unit.address == "2/26-30 Harrow Road" and unit.suburb == "Sylvania"
    assert unit.property_type == PropertyType.UNIT and unit.price.kind == PriceKind.GUIDE
    assert unit.feed_price is None  # advertised price wins
    assert (unit.lat, unit.lng, unit.land_m2) == (-34.01, 151.1, None)
    assert unit.url == "https://raywhitesutherlandshire.com.au/L1"

    assert contact.kind == ListingKind.UNDER_OFFER
    assert contact.price.kind == PriceKind.CONTACT_AGENT and contact.feed_price == 1_600_000
    assert contact.land_m2 == 556


def test_raywhite_sold_price_text():
    source = Source(name="rw", agency="Ray White", adapter="raywhite", list_urls=["https://raywhitesutherlandshire.com.au"])
    base = source.list_urls[0]

    def kind(display_price):
        value = {"id": 1, "statusCode": "CUR", "displayPrice": display_price}
        return raywhite._listing(value, source, base).kind

    assert kind("Sold | Contact Agent") == ListingKind.SOLD  # the feed still says Current
    assert kind("Auction | Unless Sold Prior") == ListingKind.FOR_SALE
    assert kind("For Sale | Contact Agent") == ListingKind.FOR_SALE


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


class SiteFetcher:
    """Serves pages by URL and records the order they were asked for."""

    def __init__(self, pages):
        self.pages = pages
        self.urls = []

    def get(self, url, method="httpx"):
        self.urls.append(url)
        return self.pages[url]


def test_highland():
    omaru, port_hacking, premier, kingsway = [
        card + "</article>" for card in (FIXTURES / "highland_cards.html").read_text().split("</article>")[:4]
    ]

    def page(*cards, next_href=None):
        link = f'<a href="{next_href}" class=next>Next</a>' if next_href else ""
        return f"<html><body>{len(cards)} Properties Found{''.join(cards)}{link}</body></html>"

    base = "https://www.highlandproperty.com.au/buying/?offices=83"
    detail = "https://www.highlandproperty.com.au/property/{}/"
    pages = {f"{base}&category={c}": page() for c in (5, 7, 19, 1)}
    pages |= {
        f"{base}&category=2": page(omaru, next_href="?offices=83&category=2&page=2"),
        "https://www.highlandproperty.com.au/buying/?offices=83&category=2&page=2": page(port_hacking),
        f"{base}&category=3": page(premier),
        base: page(omaru, port_hacking, premier, kingsway),
        detail.format("1987428/12-omaru-avenue-miranda-nsw-2228"): "<h2 class=listing-price> Auction, Unless sold prior </h2>",
        detail.format("1954393/6289-port-hacking-road-miranda-nsw-2228"):
            "<h2 class=listing-price>For Sale - $1,150,000 - $1,200,000</h2>",
        detail.format("1992662/3415-premier-street-gymea-nsw-2227"): "<h2 class=listing-price>For Sale</h2>",
    }
    fetcher = SiteFetcher(pages)
    source = Source(name="highland", agency="Highland", adapter="highland", list_urls=[base],
                    buyer_suburbs=["Miranda", "Gymea"])
    house, second_house, unit, site = highland.collect(source, fetcher, None)

    assert house.address == "12 Omaru Avenue" and house.suburb == "Miranda" and house.ref == "1987428"
    assert house.property_type == PropertyType.HOUSE and (house.beds, house.baths, house.cars) == (3, 2, 1)
    assert house.price.kind == PriceKind.AUCTION and house.kind == ListingKind.FOR_SALE
    assert house.lat and house.lng and house.photo_url.startswith("https://images.listonce.com.au/")

    assert second_house.property_type == PropertyType.HOUSE  # from page 2 of the house category
    assert (second_house.price.min, second_house.price.max) == (1_150_000, 1_200_000)

    assert unit.property_type == PropertyType.UNIT and unit.kind == ListingKind.OFF_MARKET  # the banner
    assert unit.price.kind == PriceKind.UNKNOWN and unit.price.text == "For Sale"

    # in no category and outside the buyer's suburbs: listed, but its detail page isn't fetched
    assert site.property_type is None and site.beds is None and site.price.kind == PriceKind.UNKNOWN
    assert not any("kingsway" in url for url in fetcher.urls)


def test_boxdice(monkeypatch):
    monkeypatch.setattr(boxdice, "PAGE_SIZE", 2)  # the site's batches are 15 cards
    house, under_offer, unit, shop = (
        card + "</div>" for card in (FIXTURES / "boxdice_cards.html").read_text().split("\n</div>\n")[:4]
    )

    def separator(label, value):
        return f'<div class="listing-property-separator"><strong>{label}</strong><br>{value}</div>'

    base = "https://oneagency.com.au"
    detail = base + "/listing?listing_id={}"
    pages = {
        f"{base}/listings?type=Buy&office_id=117": f"<html><body>21 properties{house}{under_offer}</body></html>",
        f"{base}/ajax-listings?offset_val=2&type=Buy&office_id=117": unit + shop,
        f"{base}/ajax-listings?offset_val=4&type=Buy&office_id=117": "\n  \n",  # nothing more
        detail.format("27214530"): (FIXTURES / "boxdice_detail.html").read_text(),
        detail.format("27423922"): separator("Property Type", "Residential") + separator("Property Category", "Apartment"),
        detail.format("19557823"): separator("Property Type", "Commercial") + separator("Property Category", "Offices"),
    }
    fetcher = SiteFetcher(pages)
    source = Source(name="oa", agency="One Agency The Shire", adapter="boxdice",
                    list_urls=[f"{base}/listings?type=Buy&office_id=117"], buyer_suburbs=["Sutherland", "Miranda"])
    listings = boxdice.collect(source, fetcher, None)
    assert [listing.ref for listing in listings] == ["27214530", "27565409", "27423922", "19557823"]
    house, under_offer, unit, shop = listings

    assert house.address == "50 Leonay Street" and house.suburb == "Sutherland"
    assert house.url == detail.format("27214530") and house.photo_url.startswith("https://assets.boxdice.com.au/")
    assert (house.beds, house.baths, house.cars) == (5, 3, 4)
    assert house.price.kind == PriceKind.ASKING and house.price.value == 1_900_000  # "FOR SALE - $1,900,000"
    assert house.property_type == PropertyType.HOUSE and house.land_m2 == 769
    assert (house.lat, house.lng) == (-34.02603375, 151.05133216)

    # Menai is outside the buyer's suburbs: card only, no detail page
    assert under_offer.kind == ListingKind.UNDER_OFFER  # the badge; the price says "AUCTION UNLESS SOLD PRIOR"
    assert under_offer.price.kind == PriceKind.AUCTION and under_offer.property_type is None
    assert detail.format("27565409") not in fetcher.urls

    assert unit.kind == ListingKind.FOR_SALE and unit.property_type == PropertyType.UNIT
    assert unit.price.kind == PriceKind.GUIDE and unit.price.min == 780_000  # "AUCTION - GUIDE $780,000"
    assert shop.property_type == PropertyType.OTHER and shop.beds is None


def test_rex(monkeypatch):
    monkeypatch.setattr(rex, "PAGE_SIZE", 1)  # the site's pages hold 12 cards
    house, off_market, apartment, land, vanity = (FIXTURES / "rex_cards.html").read_text().split("<!-- card -->")

    def page(*cards):
        return f'<html><body><input type="hidden" name="sortby">{"".join(cards)}</body></html>'

    base = "https://koreproperty.com.au/listings/?saleOrRental=Sale&status=available_under_contract&sortby=dateListed"
    pages = {f"{base}&category={category}&page=1": page() for category in rex.CATEGORIES}
    pages |= {
        f"{base}&category=House&page=1": page(house),
        f"{base}&category=House&page=2": page(off_market),
        f"{base}&category=House&page=3": page(),
        f"{base}&category=Apartment&page=1": page(apartment),
        f"{base}&category=Apartment&page=2": page(),
        f"{base}&page=1": page(off_market),
        f"{base}&page=2": page(vanity),  # a duplicate of an off-market listing under /listings/private
        f"{base}&page=3": page(land),
        f"{base}&page=4": page(),
    }
    fetcher = SiteFetcher(pages)
    source = Source(name="kore", agency="KORE", adapter="rex", list_urls=[base])
    house, off_market, apartment, land = rex.collect(source, fetcher, None)

    assert house.address == "56 Dumbarton Place" and house.suburb == "Engadine" and house.postcode == "2233"
    assert house.url == "https://koreproperty.com.au/listings/residential_sale-10P8665-engadine"
    assert house.ref == "10P8665" and house.property_type == PropertyType.HOUSE
    assert (house.beds, house.baths, house.cars, house.land_m2) == (4, 2, 1, None)  # only land cards show area
    assert house.price.kind == PriceKind.RANGE and house.price.min == 1_450_000
    assert house.kind == ListingKind.FOR_SALE and house.photo_url.startswith("https://au-crm.cdns.rexsoftware.com/")

    assert off_market.address == "12 Abbott Road" and off_market.property_type == PropertyType.HOUSE  # from page 2
    assert off_market.kind == ListingKind.OFF_MARKET  # "Off Market Opportunity"

    assert apartment.address == "12/43-49 Railway Parade" and apartment.property_type == PropertyType.UNIT

    # land has no category of its own: the link says land_sale
    assert land.property_type == PropertyType.LAND and land.address == "Lot 3008/5 Solstice Road"
    assert land.land_m2 == 354 and land.beds is None and land.price.value == 789_000
