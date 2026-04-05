from pydantic import BaseModel


class TripSearchRequest(BaseModel):
    origin_lat: float
    origin_lng: float
    destination_lat: float
    destination_lng: float
    radius_m: float | None = None
    half_angle_deg: float | None = None
    local_circle_radius_m: float | None = None
    arc_steps: int | None = None
    network_type: str | None = None
    budget: int | None = None
    walk_penalty: float | None = None


class TripSearchResponse(BaseModel):
    pickup_lat: float
    pickup_lng: float
    price: float
    walk_distance_m: float
    score: float
