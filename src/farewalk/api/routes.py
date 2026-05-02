import json
import logging
from queue import Queue
from threading import Thread
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from shapely.geometry import mapping

from farewalk.config import settings
from farewalk.models.geo import LatLng
from farewalk.schemas.roads import TripRoadGraphRequest, TripRoadGraphResponse
from farewalk.schemas.search import TripSearchRequest, TripSearchResponse
from farewalk.services.pricing import (
    PricingError,
    default_pricing_provider_id,
)
from farewalk.services.roads import get_road_graph_for_trip_search
from farewalk.services.trip_search import (
    TripSearchNotFoundError,
    execute_trip_search,
    new_search_id,
    pricing_error_event,
)

router = APIRouter()
logger = logging.getLogger(__name__)
_DONE = object()


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


def _trip_search_event_stream(payload: TripSearchRequest):
    queue: Queue[dict[str, Any] | object] = Queue()

    def emit(event: dict[str, Any]) -> None:
        queue.put(event)

    def worker() -> None:
        search_id = new_search_id()
        try:
            execution = execute_trip_search(payload, emit=emit, search_id=search_id)
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
            emit({"search_id": search_id, **pricing_error_event(exc)})
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
