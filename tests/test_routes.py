from unittest.mock import patch

import pytest

from farewalk.api.routes import (
    TripSearchNotFoundError,
    _execute_trip_search,
    _pricing_error_event,
)
from farewalk.models.geo import LatLng
from farewalk.models.road import CandidatePoint, ScoredCandidate
from farewalk.schemas.search import TripSearchRequest
from farewalk.services.pricing import PricingConfigurationError, PricingTimeoutError

MOCK_RESULT = ScoredCandidate(
    candidate=CandidatePoint(lat=40.7135, lng=-74.0050),
    price=12.50,
    walk_distance_m=95.0,
    score=60.0,
)


class MockPriceProvider:
    provider_id = "mock"

    def __call__(self, pickup: LatLng, destination: LatLng) -> float:
        return 18.75


class RaisingPriceProvider:
    def __init__(self, provider_id: str = "uber", exc: Exception | None = None):
        self.provider_id = provider_id
        self.exc = exc or PricingTimeoutError("timed out", provider_id)

    def __call__(self, pickup: LatLng, destination: LatLng) -> float:
        raise self.exc


def _payload(**overrides) -> TripSearchRequest:
    return TripSearchRequest(
        origin_lat=40.7128,
        origin_lng=-74.0060,
        destination_lat=40.7580,
        destination_lng=-73.9855,
        **overrides,
    )


def _mock_graph():
    import networkx as nx

    graph = nx.MultiDiGraph()
    graph.add_node(1, x=-74.005, y=40.7135)
    return graph


class TestExecuteTripSearch:
    def test_returns_execution_result(self):
        payload = _payload()

        with patch("farewalk.api.routes.get_road_graph_for_trip_search", return_value=(_mock_graph(), None)), \
             patch("farewalk.api.routes.generate_candidate_points", return_value=[CandidatePoint(lat=40.7135, lng=-74.005)]), \
             patch("farewalk.api.routes._select_price_provider", return_value=MockPriceProvider()), \
             patch("farewalk.api.routes.search", return_value=MOCK_RESULT):
            execution = _execute_trip_search(payload)

        assert execution.result == MOCK_RESULT
        assert execution.original_price == pytest.approx(18.75)
        assert execution.provider_id == "mock"
        assert len(execution.search_id) == 12
        assert execution.graph_node_count == 1
        assert execution.graph_edge_count == 0
        assert len(execution.candidates) == 1

    def test_no_candidates_found_raises(self):
        payload = _payload()

        with patch("farewalk.api.routes.get_road_graph_for_trip_search", return_value=(_mock_graph(), None)), \
             patch("farewalk.api.routes.generate_candidate_points", return_value=[CandidatePoint(lat=40.7135, lng=-74.005)]), \
             patch("farewalk.api.routes._select_price_provider", return_value=MockPriceProvider()), \
             patch("farewalk.api.routes.search", return_value=None):
            with pytest.raises(TripSearchNotFoundError):
                _execute_trip_search(payload)

    def test_original_price_error_bubbles_up(self):
        payload = _payload()

        with patch("farewalk.api.routes.get_road_graph_for_trip_search", return_value=(_mock_graph(), None)), \
             patch("farewalk.api.routes.generate_candidate_points", return_value=[CandidatePoint(lat=40.7135, lng=-74.005)]), \
             patch("farewalk.api.routes._select_price_provider", return_value=RaisingPriceProvider()), \
             patch("farewalk.api.routes.search", return_value=MOCK_RESULT):
            with pytest.raises(PricingTimeoutError):
                _execute_trip_search(payload)


class TestPricingErrorEvent:
    def test_formats_structured_error_event(self):
        event = _pricing_error_event(PricingConfigurationError("not configured", "uber"))
        assert event == {
            "type": "error",
            "error_type": "PricingConfigurationError",
            "provider": "uber",
            "detail": "uber pricing is not configured",
            "progress": 1.0,
        }
