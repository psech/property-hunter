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
