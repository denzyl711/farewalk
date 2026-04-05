import pytest

from farewalk.models.geo import LatLng
from farewalk.services.pricing import _BASE_FARE, _PRICE_PER_KM, stub_price_provider

NYC = LatLng(lat=40.7128, lng=-74.0060)
MIDTOWN = LatLng(lat=40.7580, lng=-73.9855)


class TestStubPriceProvider:
    def test_same_location_returns_base_fare(self):
        price = stub_price_provider(NYC, NYC)
        assert price == pytest.approx(_BASE_FARE, abs=0.01)

    def test_price_increases_with_distance(self):
        near = LatLng(lat=40.7138, lng=-74.0050)
        far = LatLng(lat=40.7580, lng=-73.9855)
        assert stub_price_provider(NYC, far) > stub_price_provider(NYC, near)

    def test_price_always_above_base_fare(self):
        assert stub_price_provider(NYC, MIDTOWN) >= _BASE_FARE

    def test_known_distance(self):
        # NYC to MIDTOWN is ~5.5km straight line
        price = stub_price_provider(NYC, MIDTOWN)
        expected_min = _BASE_FARE + _PRICE_PER_KM * 4.0
        expected_max = _BASE_FARE + _PRICE_PER_KM * 7.0
        assert expected_min < price < expected_max

    def test_roughly_symmetric(self):
        # Price A→B vs B→A should be close (haversine is symmetric)
        p1 = stub_price_provider(NYC, MIDTOWN)
        p2 = stub_price_provider(MIDTOWN, NYC)
        assert p1 == pytest.approx(p2, rel=0.01)

    def test_returns_float(self):
        assert isinstance(stub_price_provider(NYC, MIDTOWN), float)
