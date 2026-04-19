import logging
from time import perf_counter

from fastapi import APIRouter, HTTPException
from shapely.geometry import mapping

from farewalk.config import settings
from farewalk.models.geo import LatLng
from farewalk.schemas.roads import TripRoadGraphRequest, TripRoadGraphResponse
from farewalk.schemas.search import TripSearchRequest, TripSearchResponse
from farewalk.services.candidates import generate_candidate_points
from farewalk.services.pricing import stub_price_provider, uber_price_provider
from farewalk.services.roads import get_road_graph_for_trip_search
from farewalk.services.search import search

router = APIRouter()
logger = logging.getLogger(__name__)


def _select_price_provider():
    return uber_price_provider if settings.uber_cookie else stub_price_provider


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/config/defaults")
def config_defaults() -> dict[str, float | int | str | bool]:
    return {
        "network_type": settings.default_network_type,
        "radius_m": settings.default_search_radius_m,
        "half_angle_deg": settings.default_half_angle_deg,
        "local_circle_radius_m": settings.default_local_circle_radius_m,
        "arc_steps": settings.default_arc_steps,
        "road_point_spacing_m": settings.default_road_point_spacing_m,
        "budget": settings.default_search_budget,
        "walk_penalty": settings.default_walk_penalty_lambda,
        "max_leaf_size": settings.default_max_leaf_size,
        "pricing_mode": "uber" if settings.uber_cookie else "stub",
    }


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
    request_start = perf_counter()
    origin = LatLng(lat=payload.origin_lat, lng=payload.origin_lng)
    destination = LatLng(lat=payload.destination_lat, lng=payload.destination_lng)

    logger.info(
        "trip_search received origin=(%.6f, %.6f) destination=(%.6f, %.6f) "
        "radius_m=%s half_angle_deg=%s local_circle_radius_m=%s arc_steps=%s "
        "network_type=%s road_point_spacing_m=%s budget=%s walk_penalty=%s max_leaf_size=%s",
        origin.lat,
        origin.lng,
        destination.lat,
        destination.lng,
        payload.radius_m,
        payload.half_angle_deg,
        payload.local_circle_radius_m,
        payload.arc_steps,
        payload.network_type,
        payload.road_point_spacing_m,
        payload.budget,
        payload.walk_penalty,
        payload.max_leaf_size,
    )

    stage_start = perf_counter()
    graph, polygon = get_road_graph_for_trip_search(
        origin=origin,
        destination=destination,
        radius_m=payload.radius_m,
        half_angle_deg=payload.half_angle_deg,
        local_circle_radius_m=payload.local_circle_radius_m,
        arc_steps=payload.arc_steps,
        network_type=payload.network_type,
    )
    logger.info(
        "trip_search road_graph fetched nodes=%s edges=%s elapsed_s=%.2f",
        len(graph.nodes),
        len(graph.edges),
        perf_counter() - stage_start,
    )

    stage_start = perf_counter()
    candidates = generate_candidate_points(
        graph,
        origin,
        spacing_m=payload.road_point_spacing_m,
    )
    logger.info(
        "trip_search candidates generated count=%s elapsed_s=%.2f",
        len(candidates),
        perf_counter() - stage_start,
    )

    get_price = _select_price_provider()
    logger.info(
        "trip_search pricing provider=%s",
        "uber" if settings.uber_cookie else "stub",
    )

    stage_start = perf_counter()
    result = search(
        candidates=candidates,
        origin=origin,
        destination=destination,
        get_price=get_price,
        budget=payload.budget,
        walk_penalty=payload.walk_penalty,
        max_leaf_size=payload.max_leaf_size,
    )
    logger.info(
        "trip_search search completed found=%s elapsed_s=%.2f",
        result is not None,
        perf_counter() - stage_start,
    )

    if result is None:
        logger.info(
            "trip_search no candidates found total_elapsed_s=%.2f",
            perf_counter() - request_start,
        )
        raise HTTPException(status_code=404, detail="No pickup candidates found in search area")

    stage_start = perf_counter()
    original_price = get_price(origin, destination)
    logger.info(
        "trip_search original_price fetched price=%.2f elapsed_s=%.2f",
        original_price,
        perf_counter() - stage_start,
    )

    logger.info(
        "trip_search result pickup=(%.6f, %.6f) price=%.2f original_price=%.2f "
        "walk_distance_m=%.1f score=%.2f total_elapsed_s=%.2f",
        result.candidate.lat,
        result.candidate.lng,
        result.price,
        original_price,
        result.walk_distance_m,
        result.score,
        perf_counter() - request_start,
    )

    return TripSearchResponse(
        pickup_lat=result.candidate.lat,
        pickup_lng=result.candidate.lng,
        price=result.price,
        original_price=original_price,
        walk_distance_m=result.walk_distance_m,
        score=result.score,
        search_area_geojson=mapping(polygon) if polygon is not None else None,
    )
