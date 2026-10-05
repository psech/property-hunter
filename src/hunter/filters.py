"""Decides whether an enriched listing matches the buyer's criteria, and explains why not."""

from __future__ import annotations

from hunter.config import Criteria, DriveRule, TrainStopsRule, WalkRule
from hunter.models import Enriched, ListingKind


def price_for_budget(item: Enriched, rule: str) -> tuple[int | None, bool]:
    """The figure to compare with the budget, and whether it's an estimate."""
    price = item.listing.price
    if price.is_known:
        # A range or guide is judged by its lower bound: that's where negotiation starts.
        return (price.value if price.value is not None else price.low), False
    if item.estimate:
        figure = {"optimistic": item.estimate.low, "mid": item.estimate.mid, "conservative": item.estimate.high}[rule]
        return figure, True
    return None, False


def distance_ok(item: Enriched, criteria: Criteria) -> bool:
    geo = item.geo
    if not criteria.distance_rules:
        return True
    if geo.walk_min is None:
        return True  # couldn't locate it: let it through and show "distance unknown"
    for rule in criteria.distance_rules:
        if isinstance(rule, WalkRule) and geo.walk_min <= rule.max_minutes:
            return True
        if isinstance(rule, DriveRule) and geo.drive_min is not None and geo.drive_min <= rule.max_minutes:
            return True
        if (
            isinstance(rule, TrainStopsRule)
            and geo.station_walk_min is not None
            and geo.stops_to_school is not None
            and geo.station_walk_min <= rule.max_walk_to_station_minutes
            and geo.stops_to_school <= rule.max_stops
        ):
            return True
    return False


def rejection(item: Enriched, criteria: Criteria) -> str | None:
    """None when the listing matches; otherwise a short reason."""
    listing = item.listing
    if listing.kind == ListingKind.SOLD:
        return "sold"

    suburbs = {s.lower() for s in criteria.suburbs}
    if listing.suburb:
        if listing.suburb.strip().lower() not in suburbs:
            return f"suburb {listing.suburb}"
    elif not listing.kind.is_off_market:
        return "unknown suburb"

    prop = criteria.property
    if listing.property_type and prop.types and listing.property_type not in prop.types:
        return f"type {listing.property_type.value}"
    if prop.min_beds and listing.beds is not None and listing.beds < prop.min_beds:
        return f"{listing.beds} beds"
    if prop.min_baths and listing.baths is not None and listing.baths < prop.min_baths:
        return f"{listing.baths} baths"
    if prop.min_land_m2 and listing.land_m2 is not None and listing.land_m2 < prop.min_land_m2:
        return f"land {listing.land_m2:.0f} m²"

    if not distance_ok(item, criteria):
        return "too far"

    budget = criteria.budget
    if budget.max is not None:
        figure, is_estimate = price_for_budget(item, budget.estimate_rule)
        if figure is None:
            if not budget.include_unknown_price:
                return "price unknown"
        else:
            limit = budget.max * (1 + budget.tolerance) if is_estimate or not listing.price.value else budget.max
            if figure > limit:
                return "over budget"
    return None
