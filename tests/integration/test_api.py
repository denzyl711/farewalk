import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from farewalk.models.geo import LatLng
from farewalk.models.road import CandidatePoint, ScoredCandidate
from farewalk.services.pricing import (
    PricingConfigurationError,
    PricingTimeoutError,
)

ORIGIN = {"origin_lat": 40.7128, "origin_lng": -74.0060}
DESTINATION = {"destination_lat": 40.7580, "destination_lng": -73.9855}
BASE_PAYLOAD = {**ORIGIN, **DESTINATION}

MOCK_RESULT = ScoredCandidate(
    candidate=CandidatePoint(lat=40.7135, lng=-74.0050),
    price=12.50,
    walk_distance_m=95.0,
    score=60.0,
)
MOCK_ORIGINAL_PRICE = 18.75


class MockPriceProvider:
    provider_id = "mock"

    def __call__(self, pickup: LatLng, destination: LatLng) -> float:
        return MOCK_ORIGINAL_PRICE


MOCK_PRICE_PROVIDER = MockPriceProvider()


class RaisingPriceProvider:
    def __init__(self, provider_id: str = "uber", exc: Exception | None = None):
        self.provider_id = provider_id
        self.exc = exc or PricingTimeoutError("timed out", provider_id)

    def __call__(self, pickup: LatLng, destination: LatLng) -> float:
        raise self.exc


@pytest.fixture(scope="module")
def client():
    # Import the app lazily so pytest collection does not pay the full FastAPI/OSMnx import cost.
    from farewalk.main import app

    with TestClient(app) as test_client:
        yield test_client


class TestHealthEndpoint:
    def test_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestTripSearchEndpoint:
    def _mock_search(self, result=MOCK_RESULT):
        return patch("farewalk.api.routes.search", return_value=result)

    def _mock_pipeline(self, result=MOCK_RESULT):
        """Mock the full OSMnx pipeline so tests don't hit the network."""
        import networkx as nx
        mock_graph = nx.MultiDiGraph()
        mock_graph.add_node(1, x=-74.005, y=40.7135)

        graph_patch = patch(
            "farewalk.api.routes.get_road_graph_for_trip_search",
            return_value=(mock_graph, None),
        )
        candidates_patch = patch(
            "farewalk.api.routes.generate_candidate_points",
            return_value=[CandidatePoint(lat=40.7135, lng=-74.005)],
        )
        pricing_patch = patch(
            "farewalk.api.routes._select_price_provider",
            return_value=MOCK_PRICE_PROVIDER,
        )
        search_patch = patch("farewalk.api.routes.search", return_value=result)
        return graph_patch, candidates_patch, pricing_patch, search_patch

    def test_valid_request_returns_200(self, client):
        graph_p, cands_p, pricing_p, search_p = self._mock_pipeline()
        with graph_p, cands_p, pricing_p, search_p:
            response = client.post("/search/trip", json=BASE_PAYLOAD)
        assert response.status_code == 200

    def test_response_shape(self, client):
        graph_p, cands_p, pricing_p, search_p = self._mock_pipeline()
        with graph_p, cands_p, pricing_p, search_p:
            response = client.post("/search/trip", json=BASE_PAYLOAD)
        data = response.json()
        assert "pickup_lat" in data
        assert "pickup_lng" in data
        assert "price" in data
        assert "original_price" in data
        assert "walk_distance_m" in data
        assert "score" in data
        assert "search_area_geojson" in data

    def test_response_values_match_result(self, client):
        graph_p, cands_p, pricing_p, search_p = self._mock_pipeline()
        with graph_p, cands_p, pricing_p, search_p:
            response = client.post("/search/trip", json=BASE_PAYLOAD)
        data = response.json()
        assert data["pickup_lat"] == pytest.approx(MOCK_RESULT.candidate.lat)
        assert data["pickup_lng"] == pytest.approx(MOCK_RESULT.candidate.lng)
        assert data["price"] == pytest.approx(MOCK_RESULT.price)
        assert data["original_price"] == pytest.approx(MOCK_ORIGINAL_PRICE)
        assert data["walk_distance_m"] == pytest.approx(MOCK_RESULT.walk_distance_m)
        assert data["score"] == pytest.approx(MOCK_RESULT.score)
        assert data["search_area_geojson"] is None

    def test_no_candidates_returns_404(self, client):
        graph_p, cands_p, pricing_p, _ = self._mock_pipeline()
        search_p = patch("farewalk.api.routes.search", return_value=None)
        with graph_p, cands_p, pricing_p, search_p:
            response = client.post("/search/trip", json=BASE_PAYLOAD)
        assert response.status_code == 404

    def test_accepts_optional_params(self, client):
        payload = {
            **BASE_PAYLOAD,
            "budget": 5,
            "walk_penalty": 0.3,
            "radius_m": 400,
            "local_circle_radius_m": 120,
            "half_angle_deg": 45,
            "arc_steps": 16,
            "road_point_spacing_m": 25,
            "candidate_merge_radius_m": 15,
            "max_leaf_size": 4,
            "pricing_provider": "stub",
            "network_type": "drive",
        }
        graph_p, cands_p, pricing_p, search_p = self._mock_pipeline()
        with graph_p, cands_p, pricing_p, search_p:
            response = client.post("/search/trip", json=payload)
        assert response.status_code == 200

    def test_requested_pricing_provider_is_forwarded(self, client):
        graph_p, cands_p, _pricing_p, search_p = self._mock_pipeline()
        provider_patch = patch(
            "farewalk.api.routes._select_price_provider",
            return_value=MOCK_PRICE_PROVIDER,
        )
        with graph_p, cands_p, provider_patch as select_p, search_p:
            response = client.post(
                "/search/trip",
                json={**BASE_PAYLOAD, "pricing_provider": "stub"},
            )
        assert response.status_code == 200
        select_p.assert_called_once_with("stub")

    def test_auto_pricing_provider_is_forwarded(self, client):
        graph_p, cands_p, _pricing_p, search_p = self._mock_pipeline()
        provider_patch = patch(
            "farewalk.api.routes._select_price_provider",
            return_value=MOCK_PRICE_PROVIDER,
        )
        with graph_p, cands_p, provider_patch as select_p, search_p:
            response = client.post(
                "/search/trip",
                json={**BASE_PAYLOAD, "pricing_provider": "auto"},
            )
        assert response.status_code == 200
        select_p.assert_called_once_with("auto")

    def test_stream_returns_progress_events(self, client):
        graph_p, cands_p, pricing_p, search_p = self._mock_pipeline()
        with graph_p, cands_p, pricing_p, search_p:
            with client.stream("POST", "/search/trip/stream", json=BASE_PAYLOAD) as response:
                assert response.status_code == 200
                events = [
                    json.loads(line)
                    for line in response.iter_lines()
                    if line
                ]

        event_types = [event["type"] for event in events]
        assert "stage" in event_types
        assert "road_graph" in event_types
        assert "candidates" in event_types
        assert "result" in event_types
        candidates_event = next(event for event in events if event["type"] == "candidates")
        assert candidates_event["count"] == 1
        assert candidates_event["points"] == [{"lat": 40.7135, "lng": -74.005}]
        result_event = next(event for event in events if event["type"] == "result")
        assert result_event["result"]["pickup_lat"] == pytest.approx(MOCK_RESULT.candidate.lat)
        assert result_event["result"]["original_price"] == pytest.approx(MOCK_ORIGINAL_PRICE)

    def test_missing_required_fields_returns_422(self, client):
        response = client.post("/search/trip", json={"origin_lat": 40.7128})
        assert response.status_code == 422

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("radius_m", 0),
            ("half_angle_deg", 180),
            ("local_circle_radius_m", -1),
            ("arc_steps", 1),
            ("road_point_spacing_m", 0),
            ("candidate_merge_radius_m", -1),
            ("budget", 0),
            ("walk_penalty", -0.1),
            ("max_leaf_size", 0),
            ("network_type", "plane"),
            ("pricing_provider", "lyft"),
            ("origin_lat", 91),
            ("origin_lng", 181),
        ],
    )
    def test_invalid_optional_params_return_422(self, client, field, value):
        response = client.post("/search/trip", json={**BASE_PAYLOAD, field: value})
        assert response.status_code == 422

    def test_pricing_provider_configuration_error_returns_503(self, client):
        graph_p, cands_p, _pricing_p, search_p = self._mock_pipeline()
        provider_patch = patch(
            "farewalk.api.routes._select_price_provider",
            side_effect=PricingConfigurationError("not configured", "uber"),
        )
        with graph_p, cands_p, search_p, provider_patch:
            response = client.post(
                "/search/trip",
                json={**BASE_PAYLOAD, "pricing_provider": "uber"},
            )
        assert response.status_code == 503
        assert response.json()["detail"] == "uber pricing is not configured"

    def test_search_pricing_timeout_returns_504(self, client):
        graph_p, cands_p, pricing_p, _search_p = self._mock_pipeline()
        search_patch = patch(
            "farewalk.api.routes.search",
            side_effect=PricingTimeoutError("timed out", "uber"),
        )
        with graph_p, cands_p, pricing_p, search_patch:
            response = client.post("/search/trip", json=BASE_PAYLOAD)
        assert response.status_code == 504
        assert response.json()["detail"] == "uber pricing request timed out"

    def test_original_price_failure_returns_504(self, client):
        graph_p, cands_p, _pricing_p, _search_p = self._mock_pipeline()
        provider_patch = patch(
            "farewalk.api.routes._select_price_provider",
            return_value=RaisingPriceProvider("uber", PricingTimeoutError("timed out", "uber")),
        )
        search_patch = patch("farewalk.api.routes.search", return_value=MOCK_RESULT)
        with graph_p, cands_p, provider_patch, search_patch:
            response = client.post("/search/trip", json=BASE_PAYLOAD)
        assert response.status_code == 504
        assert response.json()["detail"] == "uber pricing request timed out"

    def test_stream_pricing_error_emits_structured_error(self, client):
        graph_p, cands_p, _pricing_p, search_p = self._mock_pipeline()
        provider_patch = patch(
            "farewalk.api.routes._select_price_provider",
            side_effect=PricingConfigurationError("not configured", "uber"),
        )
        with graph_p, cands_p, provider_patch, search_p:
            with client.stream(
                "POST",
                "/search/trip/stream",
                json={**BASE_PAYLOAD, "pricing_provider": "uber"},
            ) as response:
                assert response.status_code == 200
                events = [json.loads(line) for line in response.iter_lines() if line]

        error_event = next(event for event in events if event["type"] == "error")
        assert error_event["provider"] == "uber"
        assert error_event["error_type"] == "PricingConfigurationError"
        assert error_event["detail"] == "uber pricing is not configured"
