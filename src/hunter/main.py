"""Weekly run: collect → extract → enrich → filter → diff against memory → notify → save."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from hunter import valuation
from hunter.adapters import get_adapter
from hunter.cache import JsonCache
from hunter.config import Secrets, TrainStopsRule, load_criteria, load_sources, load_stations
from hunter.extract import Extractor
from hunter.filters import rejection
from hunter.geo import Geo
from hunter.llm import Llm
from hunter.mail import GmailImapSmtp
from hunter.models import Enriched, Listing
from hunter.notify.digest import Digest
from hunter.notify.whatsapp import send_whatsapp
from hunter.sources import inbox
from hunter.sources.web import Fetcher
from hunter.store import Change, Store, listing_key

log = logging.getLogger("hunter")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="hunter", description=__doc__)
    p.add_argument("--state", type=Path, default=Path("data/listings.json"), help="memory file")
    p.add_argument("--source", action="append", help="only run these sources (repeatable)")
    p.add_argument("--where", choices=["actions", "local", "all"], default="all", help="sources by run_on")
    p.add_argument("--no-inbox", action="store_true", help="skip the Gmail inbox")
    p.add_argument("--dry-run", action="store_true", help="print the digest; send and save nothing")
    p.add_argument("--seed", action="store_true", help="record everything as already sent, without notifying")
    p.add_argument("--out", type=Path, default=Path("debug/digest.html"), help="where to write the rendered digest")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def merge_duplicates(listings: list[Listing]) -> list[Listing]:
    """The same property can arrive from a web page and an email: keep one, fill gaps from the other."""
    merged: dict[str, Listing] = {}
    for listing in listings:
        key = listing_key(Enriched(listing=listing))
        if key not in merged:
            merged[key] = listing
            continue
        kept = merged[key]
        for name, value in listing:
            if getattr(kept, name) in (None, "") and value not in (None, ""):
                setattr(kept, name, value)
        if not kept.price.is_known and listing.price.is_known:
            kept.price = listing.price
        if listing.kind.is_off_market:
            kept.kind = listing.kind
    return list(merged.values())


def run(args: argparse.Namespace) -> int:
    today = date.today()
    criteria = load_criteria()
    stations = load_stations()
    secrets = Secrets.from_env()
    if criteria.budget.max is None:
        log.warning("BUDGET_MAX is not set: the budget filter is off")

    llm = Llm(secrets.gemini_api_key, criteria.llm.model, criteria.llm.max_calls_per_run)
    extract_cache, geo_cache = JsonCache("extract"), JsonCache("geo")
    extractor = Extractor(llm, extract_cache)
    geo = Geo(criteria.school, stations, secrets.ors_api_key, geo_cache)
    store = Store(args.state)

    # 1. Collect
    collected: list[Listing] = []
    healthy: set[str] = set()
    failing: list[str] = []
    fetcher = Fetcher()
    try:
        for source in load_sources():
            if not source.enabled or (args.source and source.name not in args.source):
                continue
            if args.where != "all" and source.run_on != args.where:
                continue
            try:
                found = get_adapter(source.adapter)(source, fetcher, extractor)
            except Exception as exc:  # one broken site must not stop the run
                log.error("source %s failed: %s", source.name, exc)
                failing.append(source.agency)
                continue
            log.info("%s: %d listing(s)", source.name, len(found))
            healthy.add(source.name)
            collected += found
    finally:
        fetcher.close()

    use_inbox = not args.no_inbox and not args.source and secrets.gmail_address and secrets.gmail_app_password
    new_uid = None
    if use_inbox:
        try:
            client = GmailImapSmtp(secrets.gmail_address, secrets.gmail_app_password)
            found, new_uid = inbox.collect(client, extractor, store.meta.get("inbox_last_uid", 0))
            collected += found
        except Exception as exc:
            log.error("inbox failed: %s", exc)
            failing.append("Gmail inbox")

    # 2. Enrich, remember, filter
    school_station = next((r.school_station for r in criteria.distance_rules if isinstance(r, TrainStopsRule)), None)
    changes: list[Change] = []
    seen: set[str] = set()
    unchanged = filtered = 0
    for listing in merge_duplicates(collected):
        item = Enriched(listing=listing)
        item.geo = geo.metrics(listing)
        if school_station:
            item.geo.stops_to_school = geo.stops_to(item.geo.station, school_station)
        if not listing.price.is_known:
            item.estimate = valuation.estimate(item)
        key, _ = store.observe(item, today)
        seen.add(key)
        if reason := rejection(item, criteria):
            log.debug("skip %s: %s", key, reason)
            filtered += 1
            continue
        if change := store.pending_change(key, item):
            changes.append(change)
        else:
            unchanged += 1
    gone = store.mark_missing(seen, healthy)
    log.info("%d to notify, %d unchanged, %d outside criteria, %d gone", len(changes), unchanged, filtered, gone)

    # 3. Notify
    digest = Digest.build(today, changes, unchanged_count=unchanged, filtered_count=filtered, failing_sources=failing)
    html, text = digest.render()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html)
    log.info("digest written to %s", args.out)
    extract_cache.save()  # caches aren't memory: keep them even on a dry run
    geo_cache.save()

    if args.dry_run:
        print(digest.subject())
        print(text)
        print(f"\nWhatsApp: {digest.whatsapp()}")
        return 0

    if not args.seed:
        notify(digest, html, text, secrets)
    for change in changes:
        store.mark_notified(change.key, today)

    # 4. Save (only after notifications went out, so a failed send is retried next week)
    if new_uid is not None:
        store.meta["inbox_last_uid"] = new_uid
    store.meta["last_run"] = today.isoformat()
    store.save()
    return 0


def notify(digest: Digest, html: str, text: str, secrets: Secrets) -> None:
    if secrets.gmail_address and secrets.gmail_app_password and secrets.notify_email:
        GmailImapSmtp(secrets.gmail_address, secrets.gmail_app_password).send(
            secrets.notify_email, digest.subject(), html, text
        )
        log.info("email sent")
    else:
        log.warning("email not configured: skipped")
    if secrets.callmebot_phone and secrets.callmebot_apikey:
        try:  # the email is the record; a missed ping shouldn't resend it next week
            send_whatsapp(secrets.callmebot_phone, secrets.callmebot_apikey, digest.whatsapp())
            log.info("WhatsApp sent")
        except Exception as exc:
            log.error("WhatsApp failed: %s", exc)
    else:
        log.warning("WhatsApp not configured: skipped")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpcore", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    sys.exit(run(args))


if __name__ == "__main__":
    main()
