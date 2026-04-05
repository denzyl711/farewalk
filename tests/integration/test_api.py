from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from farewalk.main import app
from farewalk.models.geo import LatLng
from farewalk.models.road import CandidatePoint, ScoredCandidate

client = TestClient(app)

ORIGIN = {"origin_lat": 40.7128, "origin_lng": -74.0060}
DESTINATION = {"destination_lat": 40.7580, "destination_lng": -73.9855}
BASE_PAYLOAD = {**ORIGIN, **DESTINATION}

MOCK_RESULT = ScoredCandidate(
    candidate=CandidatePoint(lat=40.7135, lng=-74.0050),
    price=12.50,
    walk_distance_m=95.0,
    score=60.0,
)


class TestHealthEndpoint:
    def test_returns_ok(self):
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
        search_patch = patch("farewalk.api.routes.search", return_value=result)
        return graph_patch, candidates_patch, search_patch

    def test_valid_request_returns_200(self):
        graph_p, cands_p, search_p = self._mock_pipeline()
        with graph_p, cands_p, search_p:
            response = client.post("/search/trip", json=BASE_PAYLOAD)
        assert response.status_code == 200

    def test_response_shape(self):
        graph_p, cands_p, search_p = self._mock_pipeline()
        with graph_p, cands_p, search_p:
            response = client.post("/search/trip", json=BASE_PAYLOAD)
        data = response.json()
        assert "pickup_lat" in data
        assert "pickup_lng" in data
        assert "price" in data
        assert "walk_distance_m" in data
        assert "score" in data

    def test_response_values_match_result(self):
        graph_p, cands_p, search_p = self._mock_pipeline()
        with graph_p, cands_p, search_p:
            response = client.post("/search/trip", json=BASE_PAYLOAD)
        data = response.json()
        assert data["pickup_lat"] == pytest.approx(MOCK_RESULT.candidate.lat)
        assert data["pickup_lng"] == pytest.approx(MOCK_RESULT.candidate.lng)
        assert data["price"] == pytest.approx(MOCK_RESULT.price)
        assert data["walk_distance_m"] == pytest.approx(MOCK_RESULT.walk_distance_m)
        assert data["score"] == pytest.approx(MOCK_RESULT.score)

    def test_no_candidates_returns_404(self):
        graph_p, cands_p, _ = self._mock_pipeline()
        search_p = patch("farewalk.api.routes.search", return_value=None)
        with graph_p, cands_p, search_p:
            response = client.post("/search/trip", json=BASE_PAYLOAD)
        assert response.status_code == 404

    def test_accepts_optional_params(self):
        payload = {**BASE_PAYLOAD, "budget": 5, "walk_penalty": 0.3, "radius_m": 400}
        graph_p, cands_p, search_p = self._mock_pipeline()
        with graph_p, cands_p, search_p:
            response = client.post("/search/trip", json=payload)
        assert response.status_code == 200

    def test_missing_required_fields_returns_422(self):
        response = client.post("/search/trip", json={"origin_lat": 40.7128})
        assert response.status_code == 422
