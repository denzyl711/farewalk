import pytest

from farewalk.config import settings
from farewalk.models.geo import LatLng
from farewalk.services.pricing import uber_price_provider

pytestmark = pytest.mark.skipif(
    not settings.uber_cookie,
    reason="UBER_COOKIE not set in .env",
)

PICKUP = LatLng(lat=-37.9187807, lng=145.1395933)
DESTINATION = LatLng(lat=-37.8085387, lng=144.96885)


def test_returns_positive_price():
    price = uber_price_provider(PICKUP, DESTINATION)
    assert isinstance(price, float)
    assert price > 0


def test_price_is_reasonable():
    price = uber_price_provider(PICKUP, DESTINATION)
    assert 5 < price < 500
