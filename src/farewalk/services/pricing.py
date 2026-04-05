import math

from farewalk.models.geo import LatLng

# TODO: replace with a real rideshare API client (Uber / Lyft).
# This stub approximates price as a function of straight-line distance
# to the destination so the search algorithm has something meaningful to
# optimize against during development.

_BASE_FARE = 3.50
_PRICE_PER_KM = 1.80


def stub_price_provider(pickup: LatLng, destination: LatLng) -> float:
    """Estimate fare based on straight-line distance pickup → destination."""
    dlat = math.radians(destination.lat - pickup.lat)
    dlng = math.radians(destination.lng - pickup.lng)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(pickup.lat))
        * math.cos(math.radians(destination.lat))
        * math.sin(dlng / 2) ** 2
    )
    distance_km = 6371 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return _BASE_FARE + _PRICE_PER_KM * distance_km
