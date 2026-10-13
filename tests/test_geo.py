import pytest

from hunter.geo import haversine_km, stops_between


@pytest.mark.parametrize(
    "station, stops",
    [("Kirrawee", 0), ("Gymea", 1), ("Sutherland", 1), ("Miranda", 2), ("Jannali", 2), ("Loftus", 2), ("Engadine", 3), ("Heathcote", 4)],
)
def test_stops_to_kirrawee(stations, station, stops):
    assert stops_between(stations, station, "Kirrawee") == stops


def test_haversine_school_to_station(criteria, stations):
    km = haversine_km((criteria.school.lat, criteria.school.lng), tuple(stations.stations["Kirrawee"]))
    assert 0.8 < km < 1.1


def _geo(handler, monkeypatch, tmp_path, criteria, stations):
    import httpx

    from hunter import geo as geo_module
    from hunter.cache import JsonCache

    sleeps = []
    monkeypatch.setattr(geo_module.time, "sleep", sleeps.append)
    monkeypatch.setattr(geo_module, "ORS_MIN_INTERVAL_S", 0)
    g = geo_module.Geo(criteria.school, stations, "key", JsonCache("geo", tmp_path))
    g.http = httpx.Client(transport=httpx.MockTransport(handler))
    return g, sleeps


ROUTE = {"routes": [{"summary": {"distance": 1500, "duration": 1200}}]}


def test_ors_retries_after_per_minute_limit(monkeypatch, tmp_path, criteria, stations):
    import time

    import httpx

    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"x-ratelimit-reset": str(int(time.time()) + 30)})
        return httpx.Response(200, json=ROUTE)

    g, sleeps = _geo(handler, monkeypatch, tmp_path, criteria, stations)
    assert g.route("foot-walking", (-34.04, 151.07), (-34.03, 151.07)) == (1.5, 20.0)
    assert len(calls) == 2 and 25 <= sleeps[-1] <= 31


def test_ors_daily_quota_falls_back_without_waiting(monkeypatch, tmp_path, criteria, stations):
    import time

    import httpx

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"x-ratelimit-reset": str(int(time.time()) + 6 * 3600)})

    g, sleeps = _geo(handler, monkeypatch, tmp_path, criteria, stations)
    assert g.route("foot-walking", (-34.04, 151.07), (-34.03, 151.07)) is None
    assert g.route("driving-car", (-34.04, 151.07), (-34.03, 151.07)) is None
    assert len(calls) == 1 and not [s for s in sleeps if s > 0]
