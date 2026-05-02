import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from farewalk.models.geo import LatLng
from farewalk.models.road import CandidatePoint, ScoredCandidate
from farewalk.services.pricing import PricingConfigurationError, PricingTimeoutError

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


class RaisingPriceProvider:
    def __init__(self, provider_id: str = "uber", exc: Exception | None = None):
        self.provider_id = provider_id
        self.exc = exc or PricingTimeoutError("timed out", provider_id)

    def __call__(self, pickup: LatLng, destination: LatLng) -> float:
        raise self.exc


@pytest.fixture(scope="module")
def client():
    from farewalk.main import app

    with TestClient(app) as test_client:
        yield test_client


class TestHealthEndpoint:
    def test_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestTripSearchStreamEndpoint:
    def _mock_pipeline(self, result=MOCK_RESULT):
        import networkx as nx

        mock_graph = nx.MultiDiGraph()
        mock_graph.add_node(1, x=-74.005, y=40.7135)

        graph_patch = patch(
            "farewalk.services.trip_search.get_road_graph_for_trip_search",
            return_value=(mock_graph, None),
        )
        candidates_patch = patch(
            "farewalk.services.trip_search.generate_candidate_points",
            return_value=[CandidatePoint(lat=40.7135, lng=-74.005)],
        )
        pricing_patch = patch(
            "farewalk.services.trip_search.select_price_provider",
            return_value=MockPriceProvider(),
        )
        search_patch = patch("farewalk.services.trip_search.search", return_value=result)
        return graph_patch, candidates_patch, pricing_patch, search_patch

    def _stream_events(self, client, payload):
        with client.stream("POST", "/search/trip/stream", json=payload) as response:
            assert response.status_code == 200
            return [json.loads(line) for line in response.iter_lines() if line]

    def test_stream_happy_path(self, client):
        graph_p, cands_p, pricing_p, search_p = self._mock_pipeline()
        with graph_p, cands_p, pricing_p, search_p:
            events = self._stream_events(client, BASE_PAYLOAD)

        event_types = [event["type"] for event in events]
        assert "stage" in event_types
        assert "road_graph" in event_types
        assert "candidates" in event_types
        assert "result" in event_types
        search_ids = {event["search_id"] for event in events}
        assert len(search_ids) == 1
        search_id = next(iter(search_ids))
        assert len(search_id) == 12

        result_event = next(event for event in events if event["type"] == "result")
        result = result_event["result"]
        assert result["pickup_lat"] == pytest.approx(MOCK_RESULT.candidate.lat)
        assert result["pickup_lng"] == pytest.approx(MOCK_RESULT.candidate.lng)
        assert result["price"] == pytest.approx(MOCK_RESULT.price)
        assert result["original_price"] == pytest.approx(MOCK_ORIGINAL_PRICE)
        metadata = result_event["metadata"]
        assert metadata["search_id"] == search_id
        assert metadata["provider"] == "mock"
        assert metadata["graph"] == {"nodes": 1, "edges": 0}
        assert metadata["candidates"] == {"count": 1}
        assert metadata["settings"]["budget"] == 100
        assert metadata["settings"]["pricing_provider_requested"] == "auto"
        assert metadata["timings"]["total_elapsed_s"] >= 0

    def test_stream_pricing_error(self, client):
        graph_p, cands_p, _pricing_p, search_p = self._mock_pipeline()
        provider_patch = patch(
            "farewalk.services.trip_search.select_price_provider",
            side_effect=PricingConfigurationError("not configured", "uber"),
        )
        with graph_p, cands_p, provider_patch, search_p:
            events = self._stream_events(
                client,
                {**BASE_PAYLOAD, "pricing_provider": "uber"},
            )

        error_event = next(event for event in events if event["type"] == "error")
        assert len(error_event["search_id"]) == 12
        assert error_event["provider"] == "uber"
        assert error_event["error_type"] == "PricingConfigurationError"
        assert error_event["detail"] == "uber pricing is not configured"

    def test_stream_validation_error_returns_422(self, client):
        response = client.post("/search/trip/stream", json={"origin_lat": 40.7128})
        assert response.status_code == 422


class TestRemovedSyncSearchEndpoint:
    def test_sync_search_route_is_removed(self, client):
        response = client.post("/search/trip", json=BASE_PAYLOAD)
        assert response.status_code == 404
