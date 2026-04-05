from fastapi import APIRouter, HTTPException

from farewalk.models.geo import LatLng
from farewalk.schemas.roads import TripRoadGraphRequest, TripRoadGraphResponse
from farewalk.schemas.search import TripSearchRequest, TripSearchResponse
from farewalk.services.candidates import generate_candidate_points
from farewalk.services.pricing import stub_price_provider
from farewalk.services.roads import get_road_graph_for_trip_search
from farewalk.services.search import search

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/roads/trip-graph", response_model=TripRoadGraphResponse)
def trip_graph(payload: TripRoadGraphRequest) -> TripRoadGraphResponse:
    origin = LatLng(
        lat=payload.origin_lat,
        lng=payload.origin_lng,
    )
    destination = LatLng(
        lat=payload.destination_lat,
        lng=payload.destination_lng,
    )

    graph, _polygon = get_road_graph_for_trip_search(
        origin=origin,
        destination=destination,
        radius_m=payload.radius_m,
        half_angle_deg=payload.half_angle_deg,
        local_circle_radius_m=payload.local_circle_radius_m,
        arc_steps=payload.arc_steps,
        network_type=payload.network_type,
    )

    return TripRoadGraphResponse(
        node_count=len(graph.nodes),
        edge_count=len(graph.edges),
    )


@router.post("/search/trip", response_model=TripSearchResponse)
def trip_search(payload: TripSearchRequest) -> TripSearchResponse:
    origin = LatLng(lat=payload.origin_lat, lng=payload.origin_lng)
    destination = LatLng(lat=payload.destination_lat, lng=payload.destination_lng)

    graph, _polygon = get_road_graph_for_trip_search(
        origin=origin,
        destination=destination,
        radius_m=payload.radius_m,
        half_angle_deg=payload.half_angle_deg,
        local_circle_radius_m=payload.local_circle_radius_m,
        arc_steps=payload.arc_steps,
        network_type=payload.network_type,
    )

    candidates = generate_candidate_points(graph, origin)

    result = search(
        candidates=candidates,
        origin=origin,
        destination=destination,
        get_price=stub_price_provider,
        budget=payload.budget,
        walk_penalty=payload.walk_penalty,
    )

    if result is None:
        raise HTTPException(status_code=404, detail="No pickup candidates found in search area")

    return TripSearchResponse(
        pickup_lat=result.candidate.lat,
        pickup_lng=result.candidate.lng,
        price=result.price,
        walk_distance_m=result.walk_distance_m,
        score=result.score,
    )