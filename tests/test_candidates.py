import networkx as nx
import pytest
from shapely.geometry import LineString

from farewalk.models.geo import LatLng
from farewalk.models.road import CandidatePoint
from farewalk.services.candidates import dedupe_candidate_points, generate_candidate_points

ORIGIN = LatLng(lat=40.7128, lng=-74.0060)


def _make_graph(
    nodes: dict[int, tuple[float, float]],
    edges: list[tuple[int, int]],
    geometries: dict[tuple[int, int], LineString] | None = None,
) -> nx.MultiDiGraph:
    """Build a synthetic OSMnx-style graph.

    Args:
        nodes: {node_id: (lng, lat)}
        edges: [(u, v), ...] — reverse edges added automatically
        geometries: optional {(u, v): LineString} for curved edges
    """
    G = nx.MultiDiGraph()
    for nid, (lng, lat) in nodes.items():
        G.add_node(nid, x=lng, y=lat)
    for u, v in edges:
        data = {}
        if geometries and (u, v) in geometries:
            data["geometry"] = geometries[(u, v)]
        G.add_edge(u, v, **data)
        G.add_edge(v, u, **data)
    return G


class TestGenerateCandidatePoints:
    def test_nodes_become_candidates(self):
        graph = _make_graph(
            nodes={1: (-74.006, 40.7128), 2: (-74.005, 40.7128)},
            edges=[],
        )
        candidates = generate_candidate_points(graph, ORIGIN, spacing_m=35.0)
        assert len(candidates) == 2
        assert all(isinstance(c, CandidatePoint) for c in candidates)

    def test_node_coordinates_match(self):
        graph = _make_graph(
            nodes={1: (-74.006, 40.7128)},
            edges=[],
        )
        candidates = generate_candidate_points(graph, ORIGIN, spacing_m=35.0)
        assert candidates[0].lat == pytest.approx(40.7128)
        assert candidates[0].lng == pytest.approx(-74.006)

    def test_short_edge_no_interpolation(self):
        # ~8.5m apart — too short for 35m spacing
        graph = _make_graph(
            nodes={1: (-74.0060, 40.7128), 2: (-74.00590, 40.7128)},
            edges=[(1, 2)],
        )
        candidates = generate_candidate_points(
            graph,
            ORIGIN,
            spacing_m=35.0,
            merge_radius_m=0,
        )
        # Only the 2 nodes, no interpolated points
        assert len(candidates) == 2

    def test_long_edge_produces_interpolated_points(self):
        # ~170m apart → should produce interpolated points at 35m spacing
        graph = _make_graph(
            nodes={1: (-74.006, 40.7128), 2: (-74.004, 40.7128)},
            edges=[(1, 2)],
        )
        candidates = generate_candidate_points(graph, ORIGIN, spacing_m=35.0)
        assert len(candidates) > 2  # 2 nodes + interpolated

    def test_edge_with_geometry(self):
        line = LineString([
            (-74.006, 40.7128),
            (-74.005, 40.7130),  # slight curve
            (-74.004, 40.7128),
        ])
        graph = _make_graph(
            nodes={1: (-74.006, 40.7128), 2: (-74.004, 40.7128)},
            edges=[(1, 2)],
            geometries={(1, 2): line},
        )
        candidates = generate_candidate_points(graph, ORIGIN, spacing_m=35.0)
        assert len(candidates) > 2

    def test_reverse_edges_not_duplicated(self):
        graph = _make_graph(
            nodes={1: (-74.006, 40.7128), 2: (-74.004, 40.7128)},
            edges=[(1, 2)],
        )
        result_with_reverse = generate_candidate_points(graph, ORIGIN, spacing_m=35.0)

        # Compare against a graph with only one direction
        G_single = nx.MultiDiGraph()
        G_single.add_node(1, x=-74.006, y=40.7128)
        G_single.add_node(2, x=-74.004, y=40.7128)
        G_single.add_edge(1, 2)
        result_single = generate_candidate_points(G_single, ORIGIN, spacing_m=35.0)

        assert len(result_with_reverse) == len(result_single)

    def test_uses_default_spacing_from_config(self):
        graph = _make_graph(
            nodes={1: (-74.006, 40.7128), 2: (-74.004, 40.7128)},
            edges=[(1, 2)],
        )
        # Should not raise — uses settings.default_road_point_spacing_m
        candidates = generate_candidate_points(graph, ORIGIN)
        assert len(candidates) > 2

    def test_all_candidates_near_origin(self):
        graph = _make_graph(
            nodes={1: (-74.006, 40.7128), 2: (-74.004, 40.7128)},
            edges=[(1, 2)],
        )
        candidates = generate_candidate_points(graph, ORIGIN, spacing_m=35.0)
        for c in candidates:
            assert 40.71 < c.lat < 40.72
            assert -74.01 < c.lng < -73.99

    def test_empty_graph(self):
        graph = nx.MultiDiGraph()
        candidates = generate_candidate_points(graph, ORIGIN, spacing_m=35.0)
        assert candidates == []


class TestDedupeCandidatePoints:
    def test_empty_candidates(self):
        assert dedupe_candidate_points([], ORIGIN, merge_radius_m=15) == []

    def test_zero_radius_disables_dedupe(self):
        candidates = [
            CandidatePoint(lat=40.7128, lng=-74.0060),
            CandidatePoint(lat=40.7128001, lng=-74.0060001),
        ]
        result = dedupe_candidate_points(candidates, ORIGIN, merge_radius_m=0)
        assert result == candidates

    def test_merges_nearby_candidates(self):
        candidates = [
            CandidatePoint(lat=40.7128, lng=-74.0060),
            CandidatePoint(lat=40.7128001, lng=-74.0060001),
        ]
        result = dedupe_candidate_points(candidates, ORIGIN, merge_radius_m=15)
        assert result == [candidates[0]]

    def test_keeps_far_candidates(self):
        candidates = [
            CandidatePoint(lat=40.7128, lng=-74.0060),
            CandidatePoint(lat=40.7138, lng=-74.0060),
        ]
        result = dedupe_candidate_points(candidates, ORIGIN, merge_radius_m=15)
        assert result == candidates

    def test_generate_candidate_points_dedupes_clustered_nodes(self):
        graph = _make_graph(
            nodes={
                1: (-74.0060000, 40.7128000),
                2: (-74.0060001, 40.7128001),
                3: (-74.0050000, 40.7128000),
            },
            edges=[],
        )
        candidates = generate_candidate_points(
            graph,
            ORIGIN,
            spacing_m=35.0,
            merge_radius_m=15,
        )
        assert len(candidates) == 2
