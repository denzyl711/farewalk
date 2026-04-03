import networkx as nx
from shapely.geometry import LineString

from farewalk.config import settings
from farewalk.models.geo import LatLng
from farewalk.models.road import CandidatePoint
from farewalk.utils.geo import interpolate_line_points
from farewalk.utils.projections import get_local_transformers


def generate_candidate_points(
    graph: nx.MultiDiGraph,
    origin: LatLng,
    spacing_m: float | None = None,
) -> list[CandidatePoint]:
    """Generate candidate pickup points from a road graph.

    Candidates come from two sources:
      1. Graph nodes (road intersections and endpoints).
      2. Points interpolated along edges at regular intervals.

    Args:
        graph: OSMnx road graph (MultiDiGraph with 'x'/'y' node attrs).
        origin: Used to select the local metric CRS for interpolation.
        spacing_m: Distance between interpolated edge points in meters.

    Returns:
        List of CandidatePoint instances.
    """
    if spacing_m is None:
        spacing_m = settings.default_road_point_spacing_m

    to_local, to_wgs84 = get_local_transformers(origin.lat, origin.lng)

    candidates: list[CandidatePoint] = []

    for _, data in graph.nodes(data=True):
        candidates.append(CandidatePoint(lat=data["y"], lng=data["x"]))

    seen_edges: set[tuple[int, int]] = set()
    for u, v, data in graph.edges(data=True):
        edge_key = (min(u, v), max(u, v))
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)

        if "geometry" in data:
            line = data["geometry"]
        else:
            u_data = graph.nodes[u]
            v_data = graph.nodes[v]
            line = LineString([
                (u_data["x"], u_data["y"]),
                (v_data["x"], v_data["y"]),
            ])

        interpolated = interpolate_line_points(line, spacing_m, to_local, to_wgs84)
        for lat, lng in interpolated:
            candidates.append(CandidatePoint(lat=lat, lng=lng))

    return candidates
