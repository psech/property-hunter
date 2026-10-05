"""Groups changes into digest sections and renders the email and WhatsApp texts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from hunter.store import Change

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


@dataclass
class Digest:
    run_date: date
    off_market: list[Change] = field(default_factory=list)
    new: list[Change] = field(default_factory=list)
    changed: list[Change] = field(default_factory=list)
    unchanged_count: int = 0
    filtered_count: int = 0
    failing_sources: list[str] = field(default_factory=list)

    @classmethod
    def build(cls, run_date: date, changes: list[Change], **counts) -> Digest:
        digest = cls(run_date=run_date, **counts)
        for change in sorted(changes, key=_sort_key):
            if change.item.listing.kind.is_off_market:
                digest.off_market.append(change)
            elif change.status == "new":
                digest.new.append(change)
            else:
                digest.changed.append(change)
        return digest

    @property
    def total(self) -> int:
        return len(self.off_market) + len(self.new) + len(self.changed)

    def subject(self) -> str:
        if not self.total:
            return f"Property Hunter {self.run_date:%d %b}: nothing new"
        parts = [f"{len(xs)} {label}" for xs, label in ((self.off_market, "off-market"), (self.new, "new"), (self.changed, "changed")) if xs]
        return f"Property Hunter {self.run_date:%d %b}: " + ", ".join(parts)

    def whatsapp(self) -> str:
        if not self.total:
            line = "🏠 Property Hunter: nothing new this week."
        else:
            drops = sum(1 for c in self.changed + self.off_market if any(d.startswith("price") for d in c.details))
            parts = [f"{len(self.off_market)} off-market", f"{len(self.new)} new", f"{len(self.changed)} changed"]
            if drops:
                parts.append(f"{drops} price change{'s' if drops > 1 else ''}")
            line = "🏠 Property Hunter: " + ", ".join(parts) + ". See email."
        if self.failing_sources:
            line += f" ⚠️ {len(self.failing_sources)} source(s) failing."
        return line

    def render(self) -> tuple[str, str]:
        env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
        env.filters["money"] = money
        html = env.get_template("digest.html").render(d=self)
        text = env.get_template("digest.txt").render(d=self)
        return html, text


def _sort_key(change: Change):
    geo = change.item.geo
    return (change.status != "new", geo.walk_min if geo.walk_min is not None else 999)


def money(value: int | None) -> str:
    if value is None:
        return "?"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M".replace(".00M", "M")
    return f"${value / 1_000:.0f}k"
