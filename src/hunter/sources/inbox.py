"""Reads agency off-market alert emails from the dedicated Gmail inbox."""

from __future__ import annotations

import logging
import re

from hunter.extract import Extractor, html_to_text
from hunter.mail import InboundMail, MailClient
from hunter.models import Listing, ListingKind

log = logging.getLogger(__name__)

SOURCE = "inbox"
OFF_MARKET_WORDS = re.compile(r"off[- ]?market|coming soon|pre[- ]?market|exclusive|sneak peek|before it hits", re.I)


def _agency(mail: InboundMail) -> str:
    name = re.sub(r"\s*<[^>]+>", "", mail.sender).strip().strip('"')
    return name or mail.sender


def collect(client: MailClient, extractor: Extractor, last_uid: int) -> tuple[list[Listing], int, str | None]:
    """Returns listings found in mail newer than last_uid, the new high-water UID, and an error if
    reading stopped early. Mail read before the error is kept; the rest is retried next run."""
    listings: list[Listing] = []
    if not extractor.llm.available:
        log.warning("inbox skipped: no LLM to read the emails (they'll be read next run)")
        return listings, last_uid, None
    for mail in client.fetch_since(last_uid):
        body = html_to_text(mail.html) if mail.html else (mail.text or "")
        content = f"Subject: {mail.subject}\nFrom: {mail.sender}\n\n{body}"
        hint = ListingKind.OFF_MARKET if OFF_MARKET_WORDS.search(f"{mail.subject} {body[:2000]}") else None
        try:
            found = extractor.with_llm(content, SOURCE, _agency(mail), None, hint)
        except Exception as exc:
            log.error("inbox stopped at %r: %s", mail.subject, exc)
            return listings, last_uid, str(exc)
        for listing in found:
            if not listing.url:
                listing.title = listing.title or mail.subject
        log.info("inbox: %d listing(s) in %r", len(found), mail.subject)
        listings += found
        last_uid = mail.uid
    return listings, last_uid, None
