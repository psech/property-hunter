from datetime import timedelta

from conftest import make

from hunter.store import Store


def test_new_then_unchanged(tmp_path, today):
    store = Store(tmp_path / "s.json")
    item = make()
    key, _ = store.observe(item, today)
    change = store.pending_change(key, item)
    assert change.status == "new"
    store.mark_notified(key, today)
    store.save()

    store = Store(tmp_path / "s.json")
    key, _ = store.observe(make(), today + timedelta(days=7))
    assert store.pending_change(key, make()) is None


def test_price_change_is_reported(tmp_path, today):
    store = Store(tmp_path / "s.json")
    key, _ = store.observe(make(), today)
    store.mark_notified(key, today)

    cheaper = make(price="$1,350,000")
    key, record = store.observe(cheaper, today + timedelta(days=7))
    change = store.pending_change(key, cheaper)
    assert change.status == "changed"
    assert change.details == ["price $1,400,000 → $1,350,000"]
    assert [h["price"] for h in record["history"]] == ["$1,400,000", "$1,350,000"]


def test_rewording_same_price_is_not_a_change(tmp_path, today):
    store = Store(tmp_path / "s.json")
    key, _ = store.observe(make(price="$1,400,000"), today)
    store.mark_notified(key, today)
    reworded = make(price="Asking $1.4m")
    key, _ = store.observe(reworded, today)
    assert store.pending_change(key, reworded) is None


def test_kind_change_is_reported(tmp_path, today):
    from hunter.models import ListingKind

    store = Store(tmp_path / "s.json")
    key, _ = store.observe(make(kind=ListingKind.OFF_MARKET), today)
    store.mark_notified(key, today)
    public = make(kind=ListingKind.FOR_SALE)
    key, _ = store.observe(public, today)
    assert store.pending_change(key, public).details == ["status off-market → for-sale"]


def test_address_revealed_keeps_history(tmp_path, today):
    store = Store(tmp_path / "s.json")
    hidden = make(address=None, title="Family home, Kirrawee")
    key, _ = store.observe(hidden, today)
    assert key.startswith("url:")
    store.mark_notified(key, today)

    revealed = make(address="12 Smith St")
    key, record = store.observe(revealed, today + timedelta(days=7))
    assert key == "addr:12 smith street kirrawee"
    assert len(store.listings) == 1
    assert record["first_seen"] == today.isoformat()
    assert store.pending_change(key, revealed).details == ["address — → 12 Smith St"]


def test_listings_without_address_or_url_dont_collide(tmp_path, today):
    store = Store(tmp_path / "s.json")
    a = make(address=None, url=None, ref="111")
    b = make(address=None, url=None, ref="222")
    assert store.observe(a, today)[0] == "ref:test:111"
    assert store.observe(b, today)[0] == "ref:test:222"

    revealed = make(address="9 Oak Rd", url=None, ref="111")
    key, record = store.observe(revealed, today)
    assert key == "addr:9 oak road kirrawee" and record["first_seen"] == today.isoformat()
    assert sorted(store.listings) == ["addr:9 oak road kirrawee", "ref:test:222"]


def test_disappear_and_reappear(tmp_path, today):
    store = Store(tmp_path / "s.json")
    key, _ = store.observe(make(), today)
    store.mark_notified(key, today)

    assert store.mark_missing(seen_keys=set(), healthy_sources={"other"}) == 0  # its source failed: keep
    assert store.mark_missing(seen_keys=set(), healthy_sources={"test"}) == 1
    assert store.listings[key]["active"] is False

    key, record = store.observe(make(), today + timedelta(days=14))
    assert record["active"] is True
    assert store.pending_change(key, make()) is None  # same as what was sent
