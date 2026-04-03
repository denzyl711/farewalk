from __future__ import annotations

import math

from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import transform, unary_union

from farewalk.models.geo import LatLng
from farewalk.utils.projections import get_local_transformers


def bearing_radians(origin: LatLng, destination: LatLng) -> float:
    """Compute bearing from origin to destination in radians.

    Coordinates are first projected into a local UTM coordinate system (meters)
    using the origin's latitude/longitude. This avoids distortion issues when
    working directly in geographic (lat/lng) space.

    Args:
        origin: Starting point (lat/lng)
        destination: Target point (lat/lng)

    Returns:
        Bearing from origin to destination in radians (atan2-style).
    """

    to_local, _ = get_local_transformers(origin.lat, origin.lng)

    ox_m, oy_m = to_local.transform(origin.lng, origin.lat)
    dx_m, dy_m = to_local.transform(destination.lng, destination.lat)

    return math.atan2(dy_m - oy_m, dx_m - ox_m)


def build_sector_polygon_local(
    radius_m: float,
    heading_rad: float,
    half_angle_deg: float,
    arc_steps: int,
) -> Polygon:
    """Build a local (metric) sector polygon centered at the origin (0,0).

    This function generates an isosceles sector of a circle defined by:
      - radius_m: radial distance from the origin
      - heading_rad: center direction of the sector (radians)
      - half_angle_deg: half of the cone angle (degrees)

    The returned polygon starts/ends at (0,0) and follows the arc of the sector.

    Args:
        radius_m: Radius of the sector in meters.
        heading_rad: Center heading of the sector in radians.
        half_angle_deg: Half the angular width of the sector (degrees).
        arc_steps: Number of segments to approximate the arc (must be >= 2).

    Returns:
        A Shapely Polygon in local (meter) coordinates.
    """

    if arc_steps < 2:
        raise ValueError("arc_steps must be at least 2")

    half_angle_rad = math.radians(half_angle_deg)
    start = heading_rad - half_angle_rad
    end = heading_rad + half_angle_rad

    arc_points: list[tuple[float, float]] = []
    for i in range(arc_steps + 1):
        t = i / arc_steps
        theta = start + (end - start) * t
        x = radius_m * math.cos(theta)
        y = radius_m * math.sin(theta)
        arc_points.append((x, y))

    return Polygon([(0.0, 0.0), *arc_points, (0.0, 0.0)])


def build_search_polygon(
    origin: LatLng,
    destination: LatLng,
    radius_m: float,
    half_angle_deg: float,
    local_circle_radius_m: float,
    arc_steps: int,
):
    """Build a search polygon in WGS84 (lat/lng) around an origin.

    The search area is defined as the union of:
      1) A forward-facing sector (cone) from the origin towards the destination.
      2) A circular buffer around the origin.

    The geometry is constructed in a local UTM projection (meters) to keep
    distance calculations accurate, then transformed back to WGS84.

    Args:
        origin: Starting point (lat/lng).
        destination: Target point (lat/lng) used to define the sector heading.
        radius_m: Radius of the sector in meters (must be > 0).
        half_angle_deg: Half the sector angle in degrees (0 < half_angle_deg < 180).
        local_circle_radius_m: Radius of the origin buffer in meters (>= 0).
        arc_steps: Number of segments to approximate the sector arc.

    Returns:
        A Shapely geometry (Polygon/MultiPolygon) in WGS84 coordinates.
    """

    if radius_m <= 0:
        raise ValueError("radius_m must be > 0")
    if not (0 < half_angle_deg < 180):
        raise ValueError("half_angle_deg must be between 0 and 180")
    if local_circle_radius_m < 0:
        raise ValueError("local_circle_radius_m must be >= 0")

    to_local, to_wgs84 = get_local_transformers(origin.lat, origin.lng)
    heading_rad = bearing_radians(origin, destination)

    origin_x, origin_y = to_local.transform(origin.lng, origin.lat)

    sector_local = build_sector_polygon_local(
        radius_m=radius_m,
        heading_rad=heading_rad,
        half_angle_deg=half_angle_deg,
        arc_steps=arc_steps,
    )
    sector_local = transform(lambda x, y: (x + origin_x, y + origin_y), sector_local)

    circle_local = Point(origin_x, origin_y).buffer(local_circle_radius_m)
    search_local = unary_union([sector_local, circle_local])

    return transform(to_wgs84.transform, search_local)


def interpolate_line_points(
    line: LineString,
    spacing_m: float,
    to_local: Transformer,
    to_wgs84: Transformer,
) -> list[tuple[float, float]]:
    """Interpolate evenly spaced interior points along a line.

    Projects the line into a local metric CRS for accurate spacing,
    then projects interpolated points back to WGS84.

    Endpoints are excluded — they correspond to graph nodes which are
    handled separately as candidates.

    Args:
        line: A Shapely LineString in WGS84 (lng, lat) coordinates.
        spacing_m: Distance between interpolated points in meters.
        to_local: Transformer from WGS84 to local metric CRS.
        to_wgs84: Transformer from local metric CRS to WGS84.

    Returns:
        List of (lat, lng) tuples for the interpolated points.
    """
    local_line = transform(to_local.transform, line)
    length = local_line.length

    if length <= spacing_m:
        return []

    n_points = int(length // spacing_m)
    points = []
    for i in range(1, n_points + 1):
        local_point = local_line.interpolate(i * spacing_m)
        lng, lat = to_wgs84.transform(local_point.x, local_point.y)
        points.append((lat, lng))

    return points
