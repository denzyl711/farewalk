import json
import logging
from queue import Queue
from threading import Thread
from time import perf_counter
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from shapely.geometry import mapping

from farewalk.config import settings
from farewalk.models.geo import LatLng
from farewalk.schemas.roads import TripRoadGraphRequest, TripRoadGraphResponse
from farewalk.schemas.search import TripSearchRequest, TripSearchResponse
from farewalk.services.candidates import generate_candidate_points
from farewalk.services.pricing import (
    RegisteredPricingProvider,
    default_pricing_provider_id,
    resolve_pricing_provider,
)
from farewalk.services.roads import get_road_graph_for_trip_search
from farewalk.services.search import search

router = APIRouter()
logger = logging.getLogger(__name__)
_DONE = object()


def _select_price_provider(
    requested_provider: str | None = None,
) -> RegisteredPricingProvider:
    return resolve_pricing_provider(requested_provider)


def _event_line(event: dict[str, Any]) -> str:
    return json.dumps(event, separators=(",", ":")) + "\n"


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/config/defaults")
def config_defaults() -> dict[str, float | int | str | bool]:
    provider_id = settings.default_pricing_provider
    effective_provider_id = default_pricing_provider_id()
    return {
        "network_type": settings.default_network_type,
        "radius_m": settings.default_search_radius_m,
        "half_angle_deg": settings.default_half_angle_deg,
        "local_circle_radius_m": settings.default_local_circle_radius_m,
        "arc_steps": settings.default_arc_steps,
        "road_point_spacing_m": settings.default_road_point_spacing_m,
        "candidate_merge_radius_m": settings.default_candidate_merge_radius_m,
        "budget": settings.default_search_budget,
        "walk_penalty": settings.default_walk_penalty_lambda,
        "max_leaf_size": settings.default_max_leaf_size,
        "pricing_provider": provider_id,
        "pricing_mode": effective_provider_id,
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
        "network_type=%s road_point_spacing_m=%s candidate_merge_radius_m=%s "
        "budget=%s walk_penalty=%s max_leaf_size=%s",
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
        payload.candidate_merge_radius_m,
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
        merge_radius_m=payload.candidate_merge_radius_m,
    )
    logger.info(
        "trip_search candidates generated count=%s elapsed_s=%.2f",
        len(candidates),
        perf_counter() - stage_start,
    )

    get_price = _select_price_provider(payload.pricing_provider)
    logger.info(
        "trip_search pricing provider=%s requested_provider=%s",
        get_price.provider_id,
        payload.pricing_provider,
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


def _trip_search_event_stream(payload: TripSearchRequest):
    queue: Queue[dict[str, Any] | object] = Queue()

    def emit(event: dict[str, Any]) -> None:
        queue.put(event)

    def worker() -> None:
        request_start = perf_counter()
        try:
            origin = LatLng(lat=payload.origin_lat, lng=payload.origin_lng)
            destination = LatLng(lat=payload.destination_lat, lng=payload.destination_lng)

            emit({
                "type": "stage",
                "stage": "request",
                "message": "Search request received",
                "progress": 0.03,
            })

            stage_start = perf_counter()
            emit({
                "type": "stage",
                "stage": "road_graph",
                "message": "Fetching OpenStreetMap road graph",
                "progress": 0.12,
            })
            graph, polygon = get_road_graph_for_trip_search(
                origin=origin,
                destination=destination,
                radius_m=payload.radius_m,
                half_angle_deg=payload.half_angle_deg,
                local_circle_radius_m=payload.local_circle_radius_m,
                arc_steps=payload.arc_steps,
                network_type=payload.network_type,
            )
            emit({
                "type": "road_graph",
                "nodes": len(graph.nodes),
                "edges": len(graph.edges),
                "elapsed_s": perf_counter() - stage_start,
                "search_area_geojson": mapping(polygon) if polygon is not None else None,
                "progress": 0.32,
            })

            stage_start = perf_counter()
            emit({
                "type": "stage",
                "stage": "candidates",
                "message": "Generating pickup candidates",
                "progress": 0.38,
            })
            candidates = generate_candidate_points(
                graph,
                origin,
                spacing_m=payload.road_point_spacing_m,
                merge_radius_m=payload.candidate_merge_radius_m,
            )
            emit({
                "type": "candidates",
                "count": len(candidates),
                "points": [
                    {"lat": candidate.lat, "lng": candidate.lng}
                    for candidate in candidates
                ],
                "elapsed_s": perf_counter() - stage_start,
                "progress": 0.45,
            })

            get_price = _select_price_provider(payload.pricing_provider)
            emit({
                "type": "pricing_provider",
                "provider": get_price.provider_id,
                "progress": 0.48,
            })

            result = search(
                candidates=candidates,
                origin=origin,
                destination=destination,
                get_price=get_price,
                budget=payload.budget,
                walk_penalty=payload.walk_penalty,
                max_leaf_size=payload.max_leaf_size,
                on_event=emit,
            )

            if result is None:
                emit({
                    "type": "error",
                    "detail": "No pickup candidates found in search area",
                    "progress": 1.0,
                })
                return

            stage_start = perf_counter()
            emit({
                "type": "stage",
                "stage": "original_price",
                "message": "Pricing original pickup",
                "progress": 0.95,
            })
            original_price = get_price(origin, destination)
            response = TripSearchResponse(
                pickup_lat=result.candidate.lat,
                pickup_lng=result.candidate.lng,
                price=result.price,
                original_price=original_price,
                walk_distance_m=result.walk_distance_m,
                score=result.score,
                search_area_geojson=mapping(polygon) if polygon is not None else None,
            )

            emit({
                "type": "result",
                "result": response.model_dump(),
                "original_price_elapsed_s": perf_counter() - stage_start,
                "total_elapsed_s": perf_counter() - request_start,
                "progress": 1.0,
            })
        except Exception as exc:
            logger.exception("trip_search stream failed")
            emit({
                "type": "error",
                "detail": str(exc),
                "progress": 1.0,
            })
        finally:
            queue.put(_DONE)

    Thread(target=worker, daemon=True).start()

    while True:
        event = queue.get()
        if event is _DONE:
            break
        yield _event_line(event)


@router.post("/search/trip/stream")
def trip_search_stream(payload: TripSearchRequest) -> StreamingResponse:
    return StreamingResponse(
        _trip_search_event_stream(payload),
        media_type="application/x-ndjson",
    )
