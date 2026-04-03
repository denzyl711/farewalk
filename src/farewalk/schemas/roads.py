from pydantic import BaseModel


class TripRoadGraphRequest(BaseModel):
    origin_lat: float
    origin_lng: float
    destination_lat: float
    destination_lng: float
    radius_m: float | None = None
    half_angle_deg: float | None = None
    local_circle_radius_m: float | None = None
    arc_steps: int | None = None
    network_type: str | None = None


class TripRoadGraphResponse(BaseModel):
    node_count: int
    edge_count: int