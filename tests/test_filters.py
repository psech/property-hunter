from conftest import make

from hunter.filters import rejection
from hunter.models import Estimate, ListingKind


def test_match(criteria):
    assert rejection(make(), criteria) is None


def test_suburb(criteria):
    assert rejection(make(suburb="Cronulla"), criteria) == "suburb Cronulla"


def test_unknown_suburb_only_for_off_market(criteria):
    assert rejection(make(suburb=None, address=None), criteria) == "unknown suburb"
    assert rejection(make(suburb=None, address=None, kind=ListingKind.OFF_MARKET), criteria) is None


def test_beds(criteria):
    assert rejection(make(beds=2), criteria) == "2 beds"


def test_budget_advertised_is_strict(criteria):
    assert rejection(make(price="$1,500,000"), criteria) is None
    assert rejection(make(price="$1,520,000"), criteria) == "over budget"


def test_budget_guide_uses_tolerance(criteria):
    assert rejection(make(price="Offers over $1,560,000"), criteria) is None
    assert rejection(make(price="Offers over $1,600,000"), criteria) == "over budget"


def test_budget_estimate_rule(criteria):
    item = make(price="Contact agent")
    item.estimate = Estimate(low=1_400_000, mid=1_550_000, high=1_700_000, confidence=0.6, rationale="")
    assert rejection(item, criteria) is None  # mid 1.55M <= 1.575M
    criteria.budget.estimate_rule = "conservative"
    assert rejection(item, criteria) == "over budget"


def test_unknown_price(criteria):
    assert rejection(make(price="Contact agent"), criteria) is None
    criteria.budget.include_unknown_price = False
    assert rejection(make(price="Contact agent"), criteria) == "price unknown"


def test_distance_rules_any_match(criteria):
    far = make(walk_min=60)
    far.geo.drive_min = 15
    far.geo.station, far.geo.station_walk_min, far.geo.stops_to_school = "Engadine", 5, 3
    assert rejection(far, criteria) == "too far"

    far.geo.station, far.geo.stops_to_school = "Loftus", 2  # 2 stops, 5 min walk to station
    assert rejection(far, criteria) is None

    far.geo.station_walk_min = 15  # too far from the station
    assert rejection(far, criteria) == "too far"

    far.geo.drive_min = 9
    assert rejection(far, criteria) is None
