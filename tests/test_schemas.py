import pytest
from pydantic import ValidationError

from farewalk.schemas.roads import TripRoadGraphRequest
from farewalk.schemas.search import TripSearchRequest


VALID_SEARCH = {
    "origin_lat": 40.7128,
    "origin_lng": -74.0060,
    "destination_lat": 40.7580,
    "destination_lng": -73.9855,
}


class TestTripSearchRequest:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("radius_m", 0),
            ("half_angle_deg", 180),
            ("local_circle_radius_m", -1),
            ("arc_steps", 1),
            ("road_point_spacing_m", 0),
            ("candidate_merge_radius_m", -1),
            ("budget", 0),
            ("walk_penalty", -0.1),
            ("max_leaf_size", 0),
            ("network_type", "plane"),
            ("pricing_provider", "lyft"),
            ("origin_lat", 91),
            ("origin_lng", 181),
        ],
    )
    def test_invalid_values_raise_validation_error(self, field, value):
        with pytest.raises(ValidationError):
            TripSearchRequest(**{**VALID_SEARCH, field: value})


class TestTripRoadGraphRequest:
    def test_invalid_radius_raises_validation_error(self):
        with pytest.raises(ValidationError):
            TripRoadGraphRequest(**{**VALID_SEARCH, "radius_m": 0})
