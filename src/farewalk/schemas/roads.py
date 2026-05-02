from pydantic import BaseModel

from farewalk.schemas.search import (
    ArcSteps,
    HalfAngleDeg,
    Latitude,
    Longitude,
    NetworkType,
    NonNegativeFloat,
    PositiveFloat,
)


class TripRoadGraphRequest(BaseModel):
    origin_lat: Latitude
    origin_lng: Longitude
    destination_lat: Latitude
    destination_lng: Longitude
    radius_m: PositiveFloat | None = None
    half_angle_deg: HalfAngleDeg | None = None
    local_circle_radius_m: NonNegativeFloat | None = None
    arc_steps: ArcSteps | None = None
    network_type: NetworkType | None = None


class TripRoadGraphResponse(BaseModel):
    node_count: int
    edge_count: int
