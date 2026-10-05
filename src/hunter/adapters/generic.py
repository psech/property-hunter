"""Works for most agency sites: index page → detail pages → JSON-LD, falling back to the LLM."""

from __future__ import annotations

import logging

from hunter.config import Source
from hunter.extract import Extractor, from_jsonld, html_to_text
from hunter.models import Listing, ListingKind
from hunter.sources.web import Fetcher, FetchError, links, save_debug

log = logging.getLogger(__name__)


def collect(source: Source, fetcher: Fetcher, extractor: Extractor) -> list[Listing]:
    listings: list[Listing] = []
    for list_url in source.list_urls:
        html = fetcher.get(list_url, source.fetch)
        if not source.detail_link_selector:
            # No per-listing pages to follow: read the whole index page with the LLM.
            listings += extractor.with_llm(html_to_text(html), source.name, source.agency, list_url, source.kind_hint)
            continue

        detail_urls = links(html, list_url, source.detail_link_selector)[: source.max_details]
        if not detail_urls:
            save_debug(list_url, html)
            raise FetchError(f"no listing links matched {source.detail_link_selector!r} on {list_url}")
        for url in detail_urls:
            try:
                listings += _detail(url, source, fetcher, extractor)
            except FetchError as exc:
                log.warning("%s: %s", source.name, exc)
    return [_apply_hint(listing, source.kind_hint) for listing in listings]


def _detail(url: str, source: Source, fetcher: Fetcher, extractor: Extractor) -> list[Listing]:
    html = fetcher.get(url, source.fetch)
    if listing := from_jsonld(html, source.name, source.agency, url):
        return [listing]
    found = extractor.with_llm(html_to_text(html), source.name, source.agency, url, source.kind_hint)
    for listing in found:
        listing.url = url
    return found[:1]


def _apply_hint(listing: Listing, hint: ListingKind | None) -> Listing:
    if hint and listing.kind == ListingKind.FOR_SALE:
        listing.kind = hint
    return listing
