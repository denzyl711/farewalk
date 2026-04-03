import osmnx as ox

from farewalk.config import settings
from farewalk.models.geo import LatLng
from farewalk.utils.geo import build_search_polygon


def get_road_graph_for_search_polygon(search_polygon, network_type: str):
    return ox.graph_from_polygon(search_polygon, network_type=network_type)


def get_road_graph_for_trip_search(
    origin: LatLng,
    destination: LatLng,
    radius_m: float | None = None,
    half_angle_deg: float | None = None,
    local_circle_radius_m: float | None = None,
    arc_steps: int | None = None,
    network_type: str | None = None,
):
    if radius_m is None:
        radius_m = settings.default_search_radius_m
    if half_angle_deg is None:
        half_angle_deg = settings.default_half_angle_deg
    if local_circle_radius_m is None:
        local_circle_radius_m = settings.default_local_circle_radius_m
    if arc_steps is None:
        arc_steps = settings.default_arc_steps
    if network_type is None:
        network_type = settings.default_network_type

    polygon = build_search_polygon(
        origin=origin,
        destination=destination,
        radius_m=radius_m,
        half_angle_deg=half_angle_deg,
        local_circle_radius_m=local_circle_radius_m,
        arc_steps=arc_steps,
    )

    graph = get_road_graph_for_search_polygon(
        search_polygon=polygon,
        network_type=network_type,
    )
    return graph, polygon
