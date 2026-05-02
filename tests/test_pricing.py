import httpx
import pytest

from farewalk.config import settings
from farewalk.models.geo import LatLng
from farewalk.services.pricing import (
    _BASE_FARE,
    _PRICE_PER_KM,
    PricingAuthError,
    PricingConfigurationError,
    PricingResponseError,
    PricingTimeoutError,
    default_pricing_provider_id,
    get_pricing_provider,
    resolve_pricing_provider,
    stub_price_provider,
    uber_price_provider,
)

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


class TestPricingProviderSelection:
    def test_get_pricing_provider_returns_registered_provider(self):
        provider = get_pricing_provider("stub")
        assert provider.provider_id == "stub"
        assert provider(NYC, MIDTOWN) == pytest.approx(stub_price_provider(NYC, MIDTOWN))

    def test_default_pricing_provider_id_uses_auto_cookie_state(self, monkeypatch):
        monkeypatch.setattr(settings, "default_pricing_provider", "auto")
        monkeypatch.setattr(settings, "uber_cookie", "")
        assert default_pricing_provider_id() == "stub"

        monkeypatch.setattr(settings, "uber_cookie", "cookie")
        assert default_pricing_provider_id() == "uber"

    def test_default_pricing_provider_id_respects_explicit_setting(self, monkeypatch):
        monkeypatch.setattr(settings, "default_pricing_provider", "stub")
        monkeypatch.setattr(settings, "uber_cookie", "cookie")
        assert default_pricing_provider_id() == "stub"

    def test_resolve_pricing_provider_prefers_requested_provider(self, monkeypatch):
        monkeypatch.setattr(settings, "default_pricing_provider", "stub")
        provider = resolve_pricing_provider("uber")
        assert provider.provider_id == "uber"

    def test_resolve_pricing_provider_auto_uses_default_resolution(self, monkeypatch):
        monkeypatch.setattr(settings, "default_pricing_provider", "auto")
        monkeypatch.setattr(settings, "uber_cookie", "")
        assert resolve_pricing_provider("auto").provider_id == "stub"

        monkeypatch.setattr(settings, "uber_cookie", "cookie")
        assert resolve_pricing_provider("auto").provider_id == "uber"

    def test_resolve_pricing_provider_explicit_uber_requires_cookie(self, monkeypatch):
        monkeypatch.setattr(settings, "uber_cookie", "")
        with pytest.raises(PricingConfigurationError):
            resolve_pricing_provider("uber")


class TestUberPriceProviderFailures:
    def test_timeout_maps_to_pricing_timeout_error(self, monkeypatch):
        monkeypatch.setattr(settings, "uber_cookie", "cookie")

        def fake_post(*args, **kwargs):
            raise httpx.ReadTimeout("timed out")

        monkeypatch.setattr(httpx, "post", fake_post)

        with pytest.raises(PricingTimeoutError):
            uber_price_provider(NYC, MIDTOWN)

    def test_auth_failure_maps_to_pricing_auth_error(self, monkeypatch):
        monkeypatch.setattr(settings, "uber_cookie", "cookie")

        request = httpx.Request("POST", "https://m.uber.com/go/graphql")
        response = httpx.Response(403, request=request)

        def fake_post(*args, **kwargs):
            raise httpx.HTTPStatusError("forbidden", request=request, response=response)

        monkeypatch.setattr(httpx, "post", fake_post)

        with pytest.raises(PricingAuthError):
            uber_price_provider(NYC, MIDTOWN)

    def test_malformed_response_maps_to_pricing_response_error(self, monkeypatch):
        monkeypatch.setattr(settings, "uber_cookie", "cookie")

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"data": {}}

        monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: FakeResponse())

        with pytest.raises(PricingResponseError):
            uber_price_provider(NYC, MIDTOWN)
