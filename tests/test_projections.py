import pytest
from pyproj import CRS

from farewalk.utils.projections import get_local_transformers, utm_crs_for_latlng


class TestUtmCrsForLatlng:
    def test_northern_hemisphere(self):
        # NYC: lat=40.7, lng=-74.0 → zone 18N → EPSG:32618
        crs = utm_crs_for_latlng(40.7128, -74.0060)
        assert crs == CRS.from_epsg(32618)

    def test_southern_hemisphere(self):
        # Sydney: lat=-33.8, lng=151.2 → zone 56S → EPSG:32756
        crs = utm_crs_for_latlng(-33.8688, 151.2093)
        assert crs == CRS.from_epsg(32756)

    def test_zone_boundary_negative_lng(self):
        # lng=-180 → zone 1
        crs = utm_crs_for_latlng(0.0, -180.0)
        assert crs == CRS.from_epsg(32601)

    def test_zone_boundary_positive_lng(self):
        # lng=179 → zone 60
        crs = utm_crs_for_latlng(0.0, 179.0)
        assert crs == CRS.from_epsg(32660)


class TestGetLocalTransformers:
    def test_roundtrip(self):
        lat, lng = 40.7128, -74.0060
        to_local, to_wgs84 = get_local_transformers(lat, lng)

        x, y = to_local.transform(lng, lat)
        lng_back, lat_back = to_wgs84.transform(x, y)

        assert lat_back == pytest.approx(lat, abs=1e-8)
        assert lng_back == pytest.approx(lng, abs=1e-8)

    def test_local_coords_are_in_meters(self):
        lat, lng = 40.7128, -74.0060
        to_local, _ = get_local_transformers(lat, lng)

        x1, y1 = to_local.transform(lng, lat)
        # ~0.001 degrees lng ≈ 85m at this latitude
        x2, y2 = to_local.transform(lng + 0.001, lat)

        dx = abs(x2 - x1)
        assert 80 < dx < 90
