import math

import pytest

from farewalk.models.geo import LatLng
from farewalk.models.road import CandidatePoint, ScoredCandidate
from farewalk.services.search import (
    _ZoneState,
    _pick_next_point,
    _pick_representative,
    _walking_distance_m,
    _zone_priority,
    search,
)
from farewalk.utils.spatial import KDNode, ProjectedCandidate, build_kdtree

ORIGIN = LatLng(lat=40.7128, lng=-74.0060)
DESTINATION = LatLng(lat=40.7580, lng=-73.9855)


def _cp(lat: float, lng: float) -> CandidatePoint:
    return CandidatePoint(lat=lat, lng=lng)


def _pc(x: float, y: float) -> ProjectedCandidate:
    return ProjectedCandidate(x=x, y=y, candidate=_cp(0.0, 0.0))


def _leaf(points: list[ProjectedCandidate], bounds: tuple = (0, 0, 1000, 1000)) -> KDNode:
    return KDNode(
        split_axis=None,
        split_value=None,
        bounds=bounds,
        left=None,
        right=None,
        points=points,
        is_leaf=True,
    )


# ── _walking_distance_m ────────────────────────────────────────────


class TestWalkingDistance:
    def test_same_point_is_zero(self):
        assert _walking_distance_m(100, 200, 100, 200) == 0.0

    def test_known_distance(self):
        # 3-4-5 triangle
        assert _walking_distance_m(0, 0, 3, 4) == pytest.approx(5.0)

    def test_symmetric(self):
        d1 = _walking_distance_m(0, 0, 100, 200)
        d2 = _walking_distance_m(100, 200, 0, 0)
        assert d1 == pytest.approx(d2)


# ── _pick_representative ───────────────────────────────────────────


class TestPickRepresentative:
    def test_empty_zone(self):
        zone = _leaf([])
        assert _pick_representative(zone) is None

    def test_single_point(self):
        p = _pc(500, 500)
        zone = _leaf([p])
        assert _pick_representative(zone) is p

    def test_picks_closest_to_center(self):
        center_point = _pc(500, 500)
        corner_point = _pc(10, 10)
        zone = _leaf([corner_point, center_point])
        assert _pick_representative(zone) is center_point


# ── _ZoneState ─────────────────────────────────────────────────────


class TestZoneState:
    def test_initial_state(self):
        state = _ZoneState(_leaf([_pc(0, 0)]))
        assert state.sample_count == 0
        assert state.best_score == float("inf")
        assert state.best is None

    def test_after_recording_scores(self):
        state = _ZoneState(_leaf([_pc(0, 0), _pc(100, 100)]))
        state.scores = [10.0, 5.0, 8.0]
        assert state.sample_count == 3
        assert state.best_score == 5.0

    def test_variance_single_sample(self):
        state = _ZoneState(_leaf([_pc(0, 0)]))
        state.scores = [10.0]
        assert state.variance == float("inf")

    def test_variance_multiple_samples(self):
        state = _ZoneState(_leaf([_pc(0, 0)]))
        state.scores = [10.0, 10.0, 10.0]
        assert state.variance == pytest.approx(0.0)

    def test_variance_spread(self):
        state = _ZoneState(_leaf([_pc(0, 0)]))
        state.scores = [0.0, 10.0]
        assert state.variance > 0

    def test_unsampled_points(self):
        points = [_pc(0, 0), _pc(100, 100), _pc(200, 200)]
        state = _ZoneState(_leaf(points))
        state.sampled = {0, 2}
        unsampled = state.unsampled_points()
        assert len(unsampled) == 1
        assert unsampled[0] == (1, points[1])


# ── _zone_priority ─────────────────────────────────────────────────


class TestZonePriority:
    def test_unsampled_zone_gets_exploration_bonus(self):
        sampled = _ZoneState(_leaf([_pc(0, 0)]))
        sampled.scores = [10.0]

        unsampled = _ZoneState(_leaf([_pc(0, 0)]))

        # Unsampled zone should have higher priority due to exploration bonus
        p_sampled = _zone_priority(sampled, [])
        p_unsampled = _zone_priority(unsampled, [])
        assert p_unsampled > p_sampled

    def test_cheap_zone_preferred_over_expensive(self):
        cheap = _ZoneState(_leaf([_pc(0, 0)]))
        cheap.scores = [5.0]

        expensive = _ZoneState(_leaf([_pc(0, 0)]))
        expensive.scores = [50.0]

        assert _zone_priority(cheap, []) > _zone_priority(expensive, [])

    def test_neighbor_gradient_boosts_priority(self):
        zone = _ZoneState(_leaf([_pc(0, 0)]))
        zone.scores = [20.0]

        cheap_neighbor = _ZoneState(_leaf([_pc(100, 0)]))
        cheap_neighbor.scores = [2.0]

        p_without = _zone_priority(zone, [])
        p_with = _zone_priority(zone, [cheap_neighbor])
        assert p_with > p_without


# ── _pick_next_point ───────────────────────────────────────────────


class TestPickNextPoint:
    def test_all_sampled_returns_none(self):
        state = _ZoneState(_leaf([_pc(500, 500)]))
        state.sampled = {0}
        assert _pick_next_point(state, 0, 0) is None

    def test_prefers_boundary_points(self):
        interior = _pc(500, 500)
        boundary = _pc(10, 500)  # near x_min=0
        state = _ZoneState(_leaf([interior, boundary]))
        result = _pick_next_point(state, 0, 0)
        assert result is not None
        assert result[1] is boundary


# ── search (integration) ───────────────────────────────────────────


class TestSearch:
    def _constant_price(self, price: float):
        """Price provider that always returns the same price."""
        def get_price(pickup: LatLng, destination: LatLng) -> float:
            return price
        return get_price

    def _location_based_price(self):
        """Price provider: cheaper further east (higher lng)."""
        def get_price(pickup: LatLng, destination: LatLng) -> float:
            return 20.0 - (pickup.lng + 74.006) * 1000
        return get_price

    def test_empty_candidates(self):
        result = search([], ORIGIN, DESTINATION, self._constant_price(10.0))
        assert result is None

    def test_single_candidate(self):
        candidates = [_cp(40.7130, -74.0055)]
        result = search(
            candidates, ORIGIN, DESTINATION,
            self._constant_price(10.0),
            budget=5,
        )
        assert result is not None
        assert result.candidate == candidates[0]
        assert result.price == 10.0
        assert result.score > 0

    def test_returns_scored_candidate(self):
        candidates = [_cp(40.7130, -74.005), _cp(40.7135, -74.004)]
        result = search(
            candidates, ORIGIN, DESTINATION,
            self._constant_price(10.0),
            budget=5,
        )
        assert isinstance(result, ScoredCandidate)
        assert result.price == 10.0
        assert result.walk_distance_m >= 0
        assert result.score == pytest.approx(result.price + 0.5 * result.walk_distance_m)

    def test_respects_budget(self):
        candidates = [_cp(40.7128 + i * 0.0005, -74.006 + i * 0.0005) for i in range(20)]
        call_count = 0

        def counting_price(pickup: LatLng, destination: LatLng) -> float:
            nonlocal call_count
            call_count += 1
            return 10.0

        search(candidates, ORIGIN, DESTINATION, counting_price, budget=5)
        assert call_count <= 5

    def test_prefers_cheap_nearby_point(self):
        # Close to origin, cheap
        close_cheap = _cp(40.7129, -74.0058)
        # Far from origin, cheap
        far_cheap = _cp(40.7160, -74.0020)
        # Close to origin, expensive
        close_expensive = _cp(40.7129, -74.0059)

        def price_by_point(pickup: LatLng, destination: LatLng) -> float:
            if abs(pickup.lat - close_expensive.lat) < 0.0001 and abs(pickup.lng - close_expensive.lng) < 0.0001:
                return 30.0
            return 5.0

        candidates = [close_cheap, far_cheap, close_expensive]
        result = search(
            candidates, ORIGIN, DESTINATION,
            price_by_point,
            budget=10,
            walk_penalty=0.5,
        )
        assert result is not None
        # The close+cheap point should win over far+cheap (walk penalty) and close+expensive
        assert result.candidate == close_cheap

    def test_walk_penalty_affects_score(self):
        candidates = [_cp(40.7130, -74.005)]
        low_penalty = search(
            candidates, ORIGIN, DESTINATION,
            self._constant_price(10.0),
            budget=5,
            walk_penalty=0.1,
        )
        high_penalty = search(
            candidates, ORIGIN, DESTINATION,
            self._constant_price(10.0),
            budget=5,
            walk_penalty=2.0,
        )
        assert low_penalty.score < high_penalty.score

    def test_many_candidates_returns_result(self):
        # Smoke test: lots of candidates, should not crash
        candidates = [
            _cp(40.7128 + i * 0.0002, -74.006 + j * 0.0002)
            for i in range(10)
            for j in range(10)
        ]
        result = search(
            candidates, ORIGIN, DESTINATION,
            self._constant_price(10.0),
            budget=10,
        )
        assert result is not None

    def test_finds_cheaper_zone(self):
        # Two clusters: west (expensive) and east (cheap)
        west = [_cp(40.7128, -74.006 + i * 0.0001) for i in range(5)]
        east = [_cp(40.7128, -74.003 + i * 0.0001) for i in range(5)]
        candidates = west + east

        def east_is_cheap(pickup: LatLng, destination: LatLng) -> float:
            if pickup.lng > -74.004:
                return 5.0
            return 25.0

        result = search(
            candidates, ORIGIN, DESTINATION,
            east_is_cheap,
            budget=10,
            walk_penalty=0.0,  # ignore walking to isolate price
        )
        assert result is not None
        assert result.price == 5.0
