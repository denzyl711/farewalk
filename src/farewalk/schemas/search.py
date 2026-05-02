from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

NetworkType = Literal["drive", "drive_service", "walk", "bike", "all", "all_private"]
Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]
PositiveFloat = Annotated[float, Field(gt=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]
HalfAngleDeg = Annotated[float, Field(gt=0, lt=180)]
PositiveInt = Annotated[int, Field(ge=1)]
ArcSteps = Annotated[int, Field(ge=2)]


class TripSearchRequest(BaseModel):
    origin_lat: Latitude
    origin_lng: Longitude
    destination_lat: Latitude
    destination_lng: Longitude
    radius_m: PositiveFloat | None = None
    half_angle_deg: HalfAngleDeg | None = None
    local_circle_radius_m: NonNegativeFloat | None = None
    arc_steps: ArcSteps | None = None
    network_type: NetworkType | None = None
    road_point_spacing_m: PositiveFloat | None = None
    candidate_merge_radius_m: NonNegativeFloat | None = None
    budget: PositiveInt | None = None
    walk_penalty: NonNegativeFloat | None = None
    max_leaf_size: PositiveInt | None = None
    pricing_provider: Literal["auto", "stub", "uber"] | None = None


class PickupOption(BaseModel):
    pickup_lat: float
    pickup_lng: float
    price: float
    walk_distance_m: float
    score: float
    savings: float


class TripSearchResponse(BaseModel):
    pickup_lat: float
    pickup_lng: float
    price: float
    original_price: float
    walk_distance_m: float
    score: float
    savings: float
    options: list[PickupOption] = Field(default_factory=list)
    search_area_geojson: dict[str, Any] | None = None
