"""Geocoding, travel times to the school, and train-stop counts. Results are cached permanently."""

from __future__ import annotations

import logging
import math
import time
from collections import deque

import httpx

from hunter.cache import JsonCache
from hunter.config import School, Stations
from hunter.models import GeoMetrics, Listing

log = logging.getLogger(__name__)

ORS = "https://api.openrouteservice.org"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "property-hunter/0.1 (+https://github.com/psech/property-hunter)"

# Fallbacks when routing is unavailable: typical detour factors and speeds for suburban Sydney.
WALK_DETOUR, WALK_KMH = 1.3, 4.8
DRIVE_DETOUR, DRIVE_KMH, DRIVE_OVERHEAD_MIN = 1.4, 30.0, 2.0


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def stops_between(stations: Stations, start: str, goal: str) -> int | None:
    """Fewest stops between two stations across all lines (interchanges are free)."""
    graph: dict[str, set[str]] = {}
    for line in stations.lines.values():
        for a, b in zip(line, line[1:]):
            graph.setdefault(a, set()).add(b)
            graph.setdefault(b, set()).add(a)
    seen, queue = {start}, deque([(start, 0)])
    while queue:
        node, hops = queue.popleft()
        if node == goal:
            return hops
        for nxt in graph.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, hops + 1))
    return None


class Geo:
    def __init__(self, school: School, stations: Stations, ors_key: str | None, cache: JsonCache):
        self.school = (school.lat, school.lng)
        self.stations = stations
        self.ors_key = ors_key
        self.cache = cache
        self.http = httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT})
        self._last_nominatim = 0.0

    # ----- geocoding -----

    def geocode(self, query: str) -> tuple[float, float] | None:
        key = f"geocode:{query.lower()}"
        if (hit := self.cache.get(key)) is not None:
            return tuple(hit) if hit else None
        point = self._geocode_ors(query) if self.ors_key else None
        point = point or self._geocode_nominatim(query)
        self.cache.set(key, list(point) if point else [])
        return point

    def _geocode_ors(self, query: str) -> tuple[float, float] | None:
        try:
            r = self.http.get(
                f"{ORS}/geocode/search",
                params={"api_key": self.ors_key, "text": query, "boundary.country": "AU", "size": 1},
            )
            r.raise_for_status()
            features = r.json().get("features") or []
        except httpx.HTTPError as exc:
            log.warning("ORS geocode failed for %r: %s", query, exc)
            return None
        if not features:
            return None
        lng, lat = features[0]["geometry"]["coordinates"]
        return lat, lng

    def _geocode_nominatim(self, query: str) -> tuple[float, float] | None:
        wait = 1.1 - (time.monotonic() - self._last_nominatim)  # usage policy: max 1 request/second
        if wait > 0:
            time.sleep(wait)
        self._last_nominatim = time.monotonic()
        try:
            r = self.http.get(NOMINATIM, params={"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "au"})
            r.raise_for_status()
            results = r.json()
        except httpx.HTTPError as exc:
            log.warning("Nominatim geocode failed for %r: %s", query, exc)
            return None
        return (float(results[0]["lat"]), float(results[0]["lon"])) if results else None

    # ----- routing -----

    def route(self, profile: str, a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float] | None:
        """(km, minutes) for 'foot-walking' or 'driving-car', or None without routing."""
        if not self.ors_key:
            return None
        key = f"route:{profile}:{a[0]:.5f},{a[1]:.5f}:{b[0]:.5f},{b[1]:.5f}"
        if (hit := self.cache.get(key)) is not None:
            return tuple(hit) if hit else None
        try:
            r = self.http.post(
                f"{ORS}/v2/directions/{profile}",
                headers={"Authorization": self.ors_key},
                json={"coordinates": [[a[1], a[0]], [b[1], b[0]]]},
            )
            r.raise_for_status()
            summary = r.json()["routes"][0]["summary"]
            result = (summary.get("distance", 0) / 1000, summary.get("duration", 0) / 60)
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            log.warning("ORS %s routing failed: %s", profile, exc)
            return None
        self.cache.set(key, list(result))
        return result

    # ----- enrichment -----

    def locate(self, listing: Listing) -> tuple[tuple[float, float] | None, bool]:
        """Returns (point, approx). approx=True means the suburb centroid stands in for the address."""
        if listing.lat is not None and listing.lng is not None:
            return (listing.lat, listing.lng), False
        if listing.address:
            query = listing.address
            if listing.suburb and listing.suburb.lower() not in query.lower():
                query = f"{query}, {listing.suburb}"
            if point := self.geocode(f"{query} NSW Australia"):
                return point, False
        if listing.suburb:
            return self.geocode(f"{listing.suburb} NSW Australia"), True
        return None, False

    def metrics(self, listing: Listing) -> GeoMetrics:
        point, approx = self.locate(listing)
        if point is None:
            return GeoMetrics()
        straight = haversine_km(point, self.school)
        walk = self.route("foot-walking", point, self.school)
        drive = self.route("driving-car", point, self.school)
        geo = GeoMetrics(
            lat=point[0],
            lng=point[1],
            approx=approx,
            straight_km=round(straight, 2),
            routed=walk is not None and drive is not None,
        )
        walk_km = walk[0] if walk else straight * WALK_DETOUR
        geo.walk_km = round(walk_km, 2)
        geo.walk_min = round(walk[1] if walk else walk_km / WALK_KMH * 60, 1)
        geo.drive_min = round(
            drive[1] if drive else straight * DRIVE_DETOUR / DRIVE_KMH * 60 + DRIVE_OVERHEAD_MIN, 1
        )

        name, coords = min(self.stations.stations.items(), key=lambda s: haversine_km(point, tuple(s[1])))
        station = tuple(coords)
        to_station = self.route("foot-walking", point, station)
        geo.station = name
        geo.station_walk_min = round(
            to_station[1] if to_station else haversine_km(point, station) * WALK_DETOUR / WALK_KMH * 60, 1
        )
        return geo

    def stops_to(self, station: str | None, school_station: str) -> int | None:
        return stops_between(self.stations, station, school_station) if station else None
