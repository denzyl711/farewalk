import networkx as nx
from shapely.geometry import LineString

from farewalk.config import settings
from farewalk.models.geo import LatLng
from farewalk.models.road import CandidatePoint
from farewalk.utils.geo import interpolate_line_points
from farewalk.utils.projections import get_local_transformers


def dedupe_candidate_points(
    candidates: list[CandidatePoint],
    origin: LatLng,
    merge_radius_m: float,
) -> list[CandidatePoint]:
    if merge_radius_m <= 0 or not candidates:
        return candidates

    to_local, _ = get_local_transformers(origin.lat, origin.lng)
    cell_size = merge_radius_m
    accepted: list[tuple[float, float, CandidatePoint]] = []
    grid: dict[tuple[int, int], list[int]] = {}

    for candidate in candidates:
        x, y = to_local.transform(candidate.lng, candidate.lat)
        cell = (int(x // cell_size), int(y // cell_size))

        duplicate = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for accepted_idx in grid.get((cell[0] + dx, cell[1] + dy), []):
                    accepted_x, accepted_y, _accepted_candidate = accepted[accepted_idx]
                    dist_x = x - accepted_x
                    dist_y = y - accepted_y
                    if dist_x * dist_x + dist_y * dist_y <= merge_radius_m * merge_radius_m:
                        duplicate = True
                        break
                if duplicate:
                    break
            if duplicate:
                break

        if duplicate:
            continue

        accepted_idx = len(accepted)
        accepted.append((x, y, candidate))
        grid.setdefault(cell, []).append(accepted_idx)

    return [candidate for _x, _y, candidate in accepted]


def generate_candidate_points(
    graph: nx.MultiDiGraph,
    origin: LatLng,
    spacing_m: float | None = None,
    merge_radius_m: float | None = None,
) -> list[CandidatePoint]:
    """Generate candidate pickup points from a road graph.

    Candidates come from two sources:
      1. Graph nodes (road intersections and endpoints).
      2. Points interpolated along edges at regular intervals.

    Args:
        graph: OSMnx road graph (MultiDiGraph with 'x'/'y' node attrs).
        origin: Used to select the local metric CRS for interpolation.
        spacing_m: Distance between interpolated edge points in meters.
        merge_radius_m: Merge candidates within this projected-meter radius.

    Returns:
        List of CandidatePoint instances.
    """
    if spacing_m is None:
        spacing_m = settings.default_road_point_spacing_m
    if merge_radius_m is None:
        merge_radius_m = settings.default_candidate_merge_radius_m

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

    return dedupe_candidate_points(candidates, origin, merge_radius_m)
