from __future__ import annotations

import math
from typing import Callable, Protocol

from farewalk.config import settings
from farewalk.models.geo import LatLng
from farewalk.models.road import CandidatePoint, ScoredCandidate
from farewalk.utils.spatial import (
    KDNode,
    ProjectedCandidate,
    build_kdtree,
    get_leaf_zones,
    get_neighbors,
)
from farewalk.utils.projections import get_local_transformers


class PriceProvider(Protocol):
    """Interface for getting a rideshare price quote.

    Takes a pickup point and destination, returns a price in dollars.
    Implement this with a real API client or a fake for testing.
    """

    def __call__(self, pickup: LatLng, destination: LatLng) -> float: ...


class _ZoneState:
    """Mutable tracking state for a single leaf zone during search."""

    def __init__(self, zone: KDNode):
        self.zone = zone
        self.scores: list[float] = []
        self.best: ScoredCandidate | None = None
        self.sampled: set[int] = set()  # indices into zone.points

    @property
    def sample_count(self) -> int:
        return len(self.scores)

    @property
    def best_score(self) -> float:
        if not self.scores:
            return float("inf")
        return min(self.scores)

    @property
    def variance(self) -> float:
        if len(self.scores) < 2:
            return float("inf")
        mean = sum(self.scores) / len(self.scores)
        return sum((s - mean) ** 2 for s in self.scores) / len(self.scores)

    def unsampled_points(self) -> list[tuple[int, ProjectedCandidate]]:
        return [
            (i, p) for i, p in enumerate(self.zone.points)
            if i not in self.sampled
        ]


def _walking_distance_m(
    origin_x: float,
    origin_y: float,
    point_x: float,
    point_y: float,
) -> float:
    """Euclidean distance in projected meters between origin and candidate."""
    dx = point_x - origin_x
    dy = point_y - origin_y
    return math.sqrt(dx * dx + dy * dy)


def _pick_representative(zone: KDNode) -> ProjectedCandidate | None:
    """Pick the point closest to the zone's center."""
    if not zone.points:
        return None
    x_min, y_min, x_max, y_max = zone.bounds
    cx = (x_min + x_max) / 2
    cy = (y_min + y_max) / 2
    return min(zone.points, key=lambda p: (p.x - cx) ** 2 + (p.y - cy) ** 2)


def _zone_priority(
    state: _ZoneState,
    neighbor_states: list[_ZoneState],
    exploration_weight: float = 0.3,
    gradient_weight: float = 0.2,
) -> float:
    """Compute priority for which zone to explore next.

    Higher priority = more worth exploring.
    Balances three signals:
      - Exploit: zones with low best_score
      - Explore: zones with few samples (high uncertainty)
      - Gradient: zones neighboring cheap zones
    """
    # Exploit: invert best score so lower score = higher priority
    if state.best_score == float("inf"):
        exploit = 0.0
    else:
        exploit = -state.best_score

    # Explore: fewer samples = higher uncertainty bonus
    explore = exploration_weight / (1 + state.sample_count)

    # Gradient: if neighbors are cheap, this zone might be too.
    # Lower neighbor score = cheaper = higher bonus.
    # We invert and scale so cheaper neighbors give a positive boost.
    neighbor_scores = [ns.best_score for ns in neighbor_states if ns.best_score < float("inf")]
    if neighbor_scores:
        best_neighbor = min(neighbor_scores)
        gradient = gradient_weight / (1 + best_neighbor)
    else:
        gradient = 0.0

    return exploit + explore + gradient


def _pick_next_point(state: _ZoneState, origin_x: float, origin_y: float) -> tuple[int, ProjectedCandidate] | None:
    """Pick the next unsampled point in a zone.

    Prefers points near zone boundaries (for gradient info)
    over interior points.
    """
    unsampled = state.unsampled_points()
    if not unsampled:
        return None

    x_min, y_min, x_max, y_max = state.zone.bounds

    # Score by distance to nearest boundary edge — closer to edge = better
    def boundary_closeness(p: ProjectedCandidate) -> float:
        dx = min(abs(p.x - x_min), abs(p.x - x_max))
        dy = min(abs(p.y - y_min), abs(p.y - y_max))
        return min(dx, dy)

    return min(unsampled, key=lambda pair: boundary_closeness(pair[1]))


def search(
    candidates: list[CandidatePoint],
    origin: LatLng,
    destination: LatLng,
    get_price: PriceProvider,
    budget: int | None = None,
    walk_penalty: float | None = None,
    max_leaf_size: int | None = None,
) -> ScoredCandidate | None:
    """Find the best pickup point using budgeted explore/exploit search.

    Args:
        candidates: All candidate pickup points.
        origin: Walking start point.
        destination: Rideshare destination (for price quotes).
        get_price: Callable that returns a price for a pickup→destination trip.
        budget: Max number of price API calls.
        walk_penalty: Lambda weight for walking distance in score.
        max_leaf_size: Max candidates per KD-tree leaf zone.

    Returns:
        The best ScoredCandidate found, or None if no candidates.
    """
    if not candidates:
        return None

    if budget is None:
        budget = settings.default_search_budget
    if walk_penalty is None:
        walk_penalty = settings.default_walk_penalty_lambda
    if max_leaf_size is None:
        max_leaf_size = settings.default_max_leaf_size

    # Project everything to local meters
    to_local, _ = get_local_transformers(origin.lat, origin.lng)
    origin_x, origin_y = to_local.transform(origin.lng, origin.lat)

    projected = [
        ProjectedCandidate(
            x=to_local.transform(c.lng, c.lat)[0],
            y=to_local.transform(c.lng, c.lat)[1],
            candidate=c,
        )
        for c in candidates
    ]

    # Compute bounds from the points
    xs = [p.x for p in projected]
    ys = [p.y for p in projected]
    bounds = (min(xs), min(ys), max(xs), max(ys))

    tree = build_kdtree(projected, bounds, max_leaf_size=max_leaf_size)
    zones = get_leaf_zones(tree)

    # Skip empty zones
    zone_states = {id(z): _ZoneState(z) for z in zones if z.points}
    if not zone_states:
        return None

    remaining = budget
    best_overall: ScoredCandidate | None = None

    def _score_and_record(state: _ZoneState, idx: int, point: ProjectedCandidate) -> None:
        nonlocal remaining, best_overall

        pickup = LatLng(lat=point.candidate.lat, lng=point.candidate.lng)
        price = get_price(pickup, destination)
        walk_dist = _walking_distance_m(origin_x, origin_y, point.x, point.y)
        score = price + walk_penalty * walk_dist

        scored = ScoredCandidate(
            candidate=point.candidate,
            price=price,
            walk_distance_m=walk_dist,
            score=score,
        )

        state.scores.append(score)
        state.sampled.add(idx)
        if state.best is None or score < state.best.score:
            state.best = scored
        if best_overall is None or score < best_overall.score:
            best_overall = scored

        remaining -= 1

    # ── Phase 1: sample one representative per zone ──
    for state in zone_states.values():
        if remaining <= 0:
            break
        rep = _pick_representative(state.zone)
        if rep is None:
            continue
        idx = state.zone.points.index(rep)
        _score_and_record(state, idx, rep)

    # ── Phase 2: iterative refinement ──
    while remaining > 0:
        # Build neighbor lookup for gradient scoring
        best_zone_id = None
        best_priority = float("-inf")

        for zid, state in zone_states.items():
            if not state.unsampled_points():
                continue
            neighbor_states = [
                zone_states[id(n)]
                for n in get_neighbors(tree, state.zone)
                if id(n) in zone_states
            ]
            priority = _zone_priority(state, neighbor_states)
            if priority > best_priority:
                best_priority = priority
                best_zone_id = zid

        if best_zone_id is None:
            break  # all points sampled

        state = zone_states[best_zone_id]
        next_point = _pick_next_point(state, origin_x, origin_y)
        if next_point is None:
            break
        idx, point = next_point
        _score_and_record(state, idx, point)

    return best_overall
