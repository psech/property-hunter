"""Price estimates for listings without an advertised price.

For now the only estimate is a figure the agency's own data carries but doesn't advertise
(`feed_price`, e.g. Ray White). Phase 3 adds comparable sales from the NSW Valuer General's weekly
bulk sales data, adjusted by the LLM. Listings with neither show "Price not disclosed".
"""

from __future__ import annotations

from hunter.models import Enriched, Estimate

FEED_PRICE_SPREAD = 0.05


def estimate(item: Enriched) -> Estimate | None:
    if figure := item.listing.feed_price:
        return Estimate(
            low=round(figure * (1 - FEED_PRICE_SPREAD)),
            mid=figure,
            high=round(figure * (1 + FEED_PRICE_SPREAD)),
            confidence=0.8,
            rationale="Price figure in the agency's listing data (not advertised)",
        )
    return None
