import json
import logging
from dataclasses import dataclass
from queue import Queue
from threading import Thread
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from shapely.geometry import mapping

from farewalk.config import settings
from farewalk.models.geo import LatLng
from farewalk.schemas.roads import TripRoadGraphRequest, TripRoadGraphResponse
from farewalk.schemas.search import TripSearchRequest, TripSearchResponse
from farewalk.services.candidates import generate_candidate_points
from farewalk.services.pricing import (
    PricingAuthError,
    PricingConfigurationError,
    PricingError,
    PricingResponseError,
    PricingTimeoutError,
    PricingUnavailableError,
    RegisteredPricingProvider,
    default_pricing_provider_id,
    resolve_pricing_provider,
)
from farewalk.services.roads import get_road_graph_for_trip_search
from farewalk.services.search import search

router = APIRouter()
logger = logging.getLogger(__name__)
_DONE = object()


class TripSearchNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class TripSearchExecution:
    search_id: str
    origin: LatLng
    destination: LatLng
    result: Any
    original_price: float
    polygon: Any
    candidates: list[Any]
    graph_node_count: int
    graph_edge_count: int
    provider_id: str
    resolved_settings: dict[str, Any]
    road_graph_elapsed_s: float
    candidates_elapsed_s: float
    search_elapsed_s: float
    original_price_elapsed_s: float
    total_elapsed_s: float


def _select_price_provider(
    requested_provider: str | None = None,
) -> RegisteredPricingProvider:
    return resolve_pricing_provider(requested_provider)


def _event_line(event: dict[str, Any]) -> str:
    return json.dumps(event, separators=(",", ":")) + "\n"


def _emit_search_event(
    emit: Any | None,
    search_id: str,
    event: dict[str, Any],
) -> None:
    if emit:
        emit({"search_id": search_id, **event})


def _pricing_error_detail(exc: PricingError) -> str:
    if isinstance(exc, PricingConfigurationError):
        return f"{exc.provider_id} pricing is not configured"
    if isinstance(exc, PricingTimeoutError):
        return f"{exc.provider_id} pricing request timed out"
    if isinstance(exc, PricingAuthError):
        return f"{exc.provider_id} pricing authentication failed"
    if isinstance(exc, PricingUnavailableError):
        return f"{exc.provider_id} pricing provider unavailable"
    if isinstance(exc, PricingResponseError):
        return f"{exc.provider_id} pricing response was invalid"
    return str(exc)


def _pricing_error_event(exc: PricingError) -> dict[str, Any]:
    return {
        "type": "error",
        "error_type": type(exc).__name__,
        "provider": exc.provider_id,
        "detail": _pricing_error_detail(exc),
        "progress": 1.0,
    }


def _resolved_trip_search_settings(payload: TripSearchRequest) -> dict[str, Any]:
    return {
        "radius_m": payload.radius_m if payload.radius_m is not None else settings.default_search_radius_m,
        "half_angle_deg": payload.half_angle_deg if payload.half_angle_deg is not None else settings.default_half_angle_deg,
        "local_circle_radius_m": (
            payload.local_circle_radius_m
            if payload.local_circle_radius_m is not None
            else settings.default_local_circle_radius_m
        ),
        "arc_steps": payload.arc_steps if payload.arc_steps is not None else settings.default_arc_steps,
        "network_type": payload.network_type if payload.network_type is not None else settings.default_network_type,
        "road_point_spacing_m": (
            payload.road_point_spacing_m
            if payload.road_point_spacing_m is not None
            else settings.default_road_point_spacing_m
        ),
        "candidate_merge_radius_m": (
            payload.candidate_merge_radius_m
            if payload.candidate_merge_radius_m is not None
            else settings.default_candidate_merge_radius_m
        ),
        "budget": payload.budget if payload.budget is not None else settings.default_search_budget,
        "walk_penalty": (
            payload.walk_penalty
            if payload.walk_penalty is not None
            else settings.default_walk_penalty_lambda
        ),
        "max_leaf_size": (
            payload.max_leaf_size
            if payload.max_leaf_size is not None
            else settings.default_max_leaf_size
        ),
        "pricing_provider_requested": payload.pricing_provider or settings.default_pricing_provider,
    }


def _execute_trip_search(
    payload: TripSearchRequest,
    emit: Any | None = None,
    search_id: str | None = None,
) -> TripSearchExecution:
    request_start = perf_counter()
    search_id = search_id or uuid4().hex[:12]
    origin = LatLng(lat=payload.origin_lat, lng=payload.origin_lng)
    destination = LatLng(lat=payload.destination_lat, lng=payload.destination_lng)
    resolved_settings = _resolved_trip_search_settings(payload)

    logger.info(
        "trip_search search_id=%s received origin=(%.6f, %.6f) destination=(%.6f, %.6f) "
        "radius_m=%s half_angle_deg=%s local_circle_radius_m=%s arc_steps=%s "
        "network_type=%s road_point_spacing_m=%s candidate_merge_radius_m=%s "
        "budget=%s walk_penalty=%s max_leaf_size=%s",
        search_id,
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

    _emit_search_event(emit, search_id, {
        "type": "stage",
        "stage": "request",
        "message": "Search request received",
        "progress": 0.03,
    })

    stage_start = perf_counter()
    _emit_search_event(emit, search_id, {
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
    road_graph_elapsed_s = perf_counter() - stage_start
    logger.info(
        "trip_search search_id=%s road_graph fetched nodes=%s edges=%s elapsed_s=%.2f",
        search_id,
        len(graph.nodes),
        len(graph.edges),
        road_graph_elapsed_s,
    )
    _emit_search_event(emit, search_id, {
        "type": "road_graph",
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "elapsed_s": road_graph_elapsed_s,
        "search_area_geojson": mapping(polygon) if polygon is not None else None,
        "progress": 0.32,
    })

    stage_start = perf_counter()
    _emit_search_event(emit, search_id, {
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
    candidates_elapsed_s = perf_counter() - stage_start
    logger.info(
        "trip_search search_id=%s candidates generated count=%s elapsed_s=%.2f",
        search_id,
        len(candidates),
        candidates_elapsed_s,
    )
    _emit_search_event(emit, search_id, {
        "type": "candidates",
        "count": len(candidates),
        "points": [
            {"lat": candidate.lat, "lng": candidate.lng}
            for candidate in candidates
        ],
        "elapsed_s": candidates_elapsed_s,
        "progress": 0.45,
    })

    get_price = _select_price_provider(payload.pricing_provider)
    logger.info(
        "trip_search search_id=%s pricing provider=%s requested_provider=%s",
        search_id,
        get_price.provider_id,
        payload.pricing_provider,
    )
    _emit_search_event(emit, search_id, {
        "type": "pricing_provider",
        "provider": get_price.provider_id,
        "progress": 0.48,
    })

    stage_start = perf_counter()
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
    search_elapsed_s = perf_counter() - stage_start
    logger.info(
        "trip_search search_id=%s search completed found=%s elapsed_s=%.2f",
        search_id,
        result is not None,
        search_elapsed_s,
    )

    if result is None:
        logger.info(
            "trip_search search_id=%s no candidates found total_elapsed_s=%.2f",
            search_id,
            perf_counter() - request_start,
        )
        raise TripSearchNotFoundError("No pickup candidates found in search area")

    stage_start = perf_counter()
    _emit_search_event(emit, search_id, {
        "type": "stage",
        "stage": "original_price",
        "message": "Pricing original pickup",
        "progress": 0.95,
    })
    original_price = get_price(origin, destination)
    original_price_elapsed_s = perf_counter() - stage_start
    logger.info(
        "trip_search search_id=%s original_price fetched price=%.2f elapsed_s=%.2f",
        search_id,
        original_price,
        original_price_elapsed_s,
    )

    logger.info(
        "trip_search search_id=%s result pickup=(%.6f, %.6f) price=%.2f original_price=%.2f "
        "walk_distance_m=%.1f score=%.2f total_elapsed_s=%.2f",
        search_id,
        result.candidate.lat,
        result.candidate.lng,
        result.price,
        original_price,
        result.walk_distance_m,
        result.score,
        perf_counter() - request_start,
    )

    return TripSearchExecution(
        search_id=search_id,
        origin=origin,
        destination=destination,
        result=result,
        original_price=original_price,
        polygon=polygon,
        candidates=candidates,
        graph_node_count=len(graph.nodes),
        graph_edge_count=len(graph.edges),
        provider_id=get_price.provider_id,
        resolved_settings=resolved_settings,
        road_graph_elapsed_s=road_graph_elapsed_s,
        candidates_elapsed_s=candidates_elapsed_s,
        search_elapsed_s=search_elapsed_s,
        original_price_elapsed_s=original_price_elapsed_s,
        total_elapsed_s=perf_counter() - request_start,
    )


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


def _trip_search_event_stream(payload: TripSearchRequest):
    queue: Queue[dict[str, Any] | object] = Queue()

    def emit(event: dict[str, Any]) -> None:
        queue.put(event)

    def worker() -> None:
        search_id = uuid4().hex[:12]
        try:
            execution = _execute_trip_search(payload, emit=emit, search_id=search_id)
            response = TripSearchResponse(
                pickup_lat=execution.result.candidate.lat,
                pickup_lng=execution.result.candidate.lng,
                price=execution.result.price,
                original_price=execution.original_price,
                walk_distance_m=execution.result.walk_distance_m,
                score=execution.result.score,
                search_area_geojson=mapping(execution.polygon) if execution.polygon is not None else None,
            )

            emit({
                "search_id": execution.search_id,
                "type": "result",
                "result": response.model_dump(),
                "metadata": {
                    "search_id": execution.search_id,
                    "provider": execution.provider_id,
                    "graph": {
                        "nodes": execution.graph_node_count,
                        "edges": execution.graph_edge_count,
                    },
                    "candidates": {
                        "count": len(execution.candidates),
                    },
                    "timings": {
                        "road_graph_elapsed_s": execution.road_graph_elapsed_s,
                        "candidates_elapsed_s": execution.candidates_elapsed_s,
                        "search_elapsed_s": execution.search_elapsed_s,
                        "original_price_elapsed_s": execution.original_price_elapsed_s,
                        "total_elapsed_s": execution.total_elapsed_s,
                    },
                    "settings": execution.resolved_settings,
                },
                "original_price_elapsed_s": execution.original_price_elapsed_s,
                "total_elapsed_s": execution.total_elapsed_s,
                "progress": 1.0,
            })
        except TripSearchNotFoundError as exc:
            emit({
                "search_id": search_id,
                "type": "error",
                "detail": str(exc),
                "progress": 1.0,
            })
        except PricingError as exc:
            emit({"search_id": search_id, **_pricing_error_event(exc)})
        except Exception as exc:
            logger.exception("trip_search stream failed")
            emit({
                "search_id": search_id,
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
