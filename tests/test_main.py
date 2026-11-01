from hunter.main import merge_duplicates
from hunter.models import Listing, ListingKind


def _listing(source, kind):
    return Listing(source=source, address="3 Kendall Place", suburb="Kareela", kind=kind)


def test_a_withdrawn_record_never_hides_a_live_listing():
    for order in (("pulse", "rw"), ("rw", "pulse")):
        kinds = {"pulse": ListingKind.WITHDRAWN, "rw": ListingKind.FOR_SALE}
        (merged,) = merge_duplicates([_listing(source, kinds[source]) for source in order])
        assert merged.kind == ListingKind.FOR_SALE


def test_live_off_market_still_wins_over_for_sale():
    (merged,) = merge_duplicates([_listing("a", ListingKind.FOR_SALE), _listing("b", ListingKind.OFF_MARKET)])
    assert merged.kind == ListingKind.OFF_MARKET
