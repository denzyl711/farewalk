import math

import pytest
from shapely.geometry import LineString, Point

from farewalk.models.geo import LatLng
from farewalk.utils.geo import (
    bearing_radians,
    build_search_polygon,
    build_sector_polygon_local,
    interpolate_line_points,
)
from farewalk.utils.projections import get_local_transformers

# Reference points: NYC area
ORIGIN = LatLng(lat=40.7128, lng=-74.0060)
EAST_OF_ORIGIN = LatLng(lat=40.7128, lng=-73.9960)
NORTH_OF_ORIGIN = LatLng(lat=40.7228, lng=-74.0060)


# --- bearing_radians ---


class TestBearingRadians:
    def test_due_east(self):
        bearing = bearing_radians(ORIGIN, EAST_OF_ORIGIN)
        assert bearing == pytest.approx(0.0, abs=0.02)

    def test_due_north(self):
        bearing = bearing_radians(ORIGIN, NORTH_OF_ORIGIN)
        assert bearing == pytest.approx(math.pi / 2, abs=0.02)

    def test_due_west(self):
        west = LatLng(lat=40.7128, lng=-74.0160)
        bearing = bearing_radians(ORIGIN, west)
        assert abs(bearing) == pytest.approx(math.pi, abs=0.02)

    def test_due_south(self):
        south = LatLng(lat=40.7028, lng=-74.0060)
        bearing = bearing_radians(ORIGIN, south)
        assert bearing == pytest.approx(-math.pi / 2, abs=0.02)


# --- build_sector_polygon_local ---


class TestBuildSectorPolygonLocal:
    def test_valid_polygon(self):
        poly = build_sector_polygon_local(
            radius_m=500, heading_rad=0.0, half_angle_deg=45, arc_steps=8
        )
        assert poly.is_valid
        assert not poly.is_empty

    def test_contains_origin(self):
        poly = build_sector_polygon_local(
            radius_m=500, heading_rad=0.0, half_angle_deg=45, arc_steps=8
        )
        assert poly.contains(Point(0.0, 0.0)) or poly.touches(Point(0.0, 0.0))

    def test_point_along_heading_inside(self):
        poly = build_sector_polygon_local(
            radius_m=500, heading_rad=0.0, half_angle_deg=45, arc_steps=8
        )
        assert poly.contains(Point(250, 0))

    def test_point_opposite_heading_outside(self):
        poly = build_sector_polygon_local(
            radius_m=500, heading_rad=0.0, half_angle_deg=45, arc_steps=8
        )
        assert not poly.contains(Point(-250, 0))

    def test_arc_steps_too_low(self):
        with pytest.raises(ValueError, match="arc_steps"):
            build_sector_polygon_local(
                radius_m=500, heading_rad=0.0, half_angle_deg=45, arc_steps=1
            )

    def test_area_scales_with_angle(self):
        narrow = build_sector_polygon_local(
            radius_m=500, heading_rad=0.0, half_angle_deg=30, arc_steps=24
        )
        wide = build_sector_polygon_local(
            radius_m=500, heading_rad=0.0, half_angle_deg=60, arc_steps=24
        )
        assert wide.area > narrow.area


# --- build_search_polygon ---


class TestBuildSearchPolygon:
    def test_valid_wgs84_polygon(self):
        poly = build_search_polygon(
            origin=ORIGIN,
            destination=EAST_OF_ORIGIN,
            radius_m=500,
            half_angle_deg=60,
            local_circle_radius_m=100,
            arc_steps=24,
        )
        assert poly.is_valid
        assert not poly.is_empty

    def test_contains_origin(self):
        poly = build_search_polygon(
            origin=ORIGIN,
            destination=EAST_OF_ORIGIN,
            radius_m=500,
            half_angle_deg=60,
            local_circle_radius_m=100,
            arc_steps=24,
        )
        assert poly.contains(Point(ORIGIN.lng, ORIGIN.lat))

    def test_invalid_radius(self):
        with pytest.raises(ValueError, match="radius_m"):
            build_search_polygon(
                origin=ORIGIN,
                destination=EAST_OF_ORIGIN,
                radius_m=0,
                half_angle_deg=60,
                local_circle_radius_m=100,
                arc_steps=24,
            )

    def test_invalid_half_angle(self):
        with pytest.raises(ValueError, match="half_angle_deg"):
            build_search_polygon(
                origin=ORIGIN,
                destination=EAST_OF_ORIGIN,
                radius_m=500,
                half_angle_deg=0,
                local_circle_radius_m=100,
                arc_steps=24,
            )

    def test_invalid_circle_radius(self):
        with pytest.raises(ValueError, match="local_circle_radius_m"):
            build_search_polygon(
                origin=ORIGIN,
                destination=EAST_OF_ORIGIN,
                radius_m=500,
                half_angle_deg=60,
                local_circle_radius_m=-1,
                arc_steps=24,
            )

    def test_zero_circle_radius_still_valid(self):
        poly = build_search_polygon(
            origin=ORIGIN,
            destination=EAST_OF_ORIGIN,
            radius_m=500,
            half_angle_deg=60,
            local_circle_radius_m=0,
            arc_steps=24,
        )
        assert poly.is_valid


# --- interpolate_line_points ---


class TestInterpolateLinePoints:
    @pytest.fixture()
    def transformers(self):
        return get_local_transformers(ORIGIN.lat, ORIGIN.lng)

    def test_short_line_returns_empty(self, transformers):
        to_local, to_wgs84 = transformers
        # ~10m line, spacing=35m → no interior points
        line = LineString([
            (ORIGIN.lng, ORIGIN.lat),
            (ORIGIN.lng + 0.0001, ORIGIN.lat),
        ])
        result = interpolate_line_points(line, 35.0, to_local, to_wgs84)
        assert result == []

    def test_long_line_returns_points(self, transformers):
        to_local, to_wgs84 = transformers
        # ~170m line, spacing=35m → 4 interior points
        line = LineString([
            (ORIGIN.lng, ORIGIN.lat),
            (ORIGIN.lng + 0.002, ORIGIN.lat),
        ])
        result = interpolate_line_points(line, 35.0, to_local, to_wgs84)
        assert len(result) >= 3

    def test_points_are_between_endpoints(self, transformers):
        to_local, to_wgs84 = transformers
        lng_start = ORIGIN.lng
        lng_end = ORIGIN.lng + 0.002
        line = LineString([(lng_start, ORIGIN.lat), (lng_end, ORIGIN.lat)])

        result = interpolate_line_points(line, 35.0, to_local, to_wgs84)
        for lat, lng in result:
            assert lat == pytest.approx(ORIGIN.lat, abs=1e-5)
            assert lng_start < lng < lng_end

    def test_returns_lat_lng_tuples(self, transformers):
        to_local, to_wgs84 = transformers
        line = LineString([
            (ORIGIN.lng, ORIGIN.lat),
            (ORIGIN.lng + 0.002, ORIGIN.lat),
        ])
        result = interpolate_line_points(line, 35.0, to_local, to_wgs84)
        for point in result:
            assert len(point) == 2
            lat, lng = point
            assert 40 < lat < 41
            assert -75 < lng < -73
