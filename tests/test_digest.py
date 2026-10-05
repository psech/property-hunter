from conftest import make

from hunter.models import ListingKind
from hunter.notify.digest import Digest
from hunter.store import Change


def test_sections_put_off_market_first(today):
    changes = [
        Change("a", make(address="1 A St"), "new"),
        Change("b", make(address="2 B St", kind=ListingKind.OFF_MARKET), "changed", ["price $1.5M → $1.4M"]),
        Change("c", make(address="3 C St"), "changed", ["price $1.45M → $1.40M"]),
        Change("d", make(address="4 D St", kind=ListingKind.COMING_SOON), "new"),
    ]
    digest = Digest.build(today, changes)
    assert [c.key for c in digest.off_market] == ["d", "b"]  # new before changed
    assert [c.key for c in digest.new] == ["a"]
    assert [c.key for c in digest.changed] == ["c"]

    html, text = digest.render()
    assert html.index("Off-market") < html.index("New (") < html.index("Changed (")
    assert text.index("OFF-MARKET") < text.index("== NEW") < text.index("== CHANGED")
    assert digest.whatsapp() == "🏠 Property Hunter: 2 off-market, 1 new, 1 changed, 2 price changes. See email."


def test_empty_digest_is_a_heartbeat(today):
    digest = Digest.build(today, [], failing_sources=["Pulse"])
    assert digest.subject().endswith("nothing new")
    assert digest.whatsapp() == "🏠 Property Hunter: nothing new this week. ⚠️ 1 source(s) failing."
    digest.render()
