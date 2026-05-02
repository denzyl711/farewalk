# farewalk

farewalk is a personal FastAPI app for finding cheaper rideshare pickup points near a trip origin.

Given an origin and destination, the backend builds a directional search area, fetches a drivable OpenStreetMap road graph, generates possible pickup candidates, prices a budgeted subset of those candidates, and returns a ranked shortlist of pickup points.

The frontend is a single Leaflet page served by the backend. This README focuses on the backend.

## Core Idea

Rideshare prices can change based on pickup location. Instead of always requesting pickup at the exact origin, farewalk searches nearby road-accessible points that the user can walk to.

The score used for ranking is:

```text
score = trip_price + walk_penalty * walking_distance_m
```

Lower score is better.

Important: the returned shortlist is the best sampled set from a budgeted search, not a mathematically guaranteed global optimum.

## Runtime Flow

One streamed search request follows this path:

```text
POST /search/trip/stream
  -> validate request with Pydantic
  -> create search_id
  -> build origin/destination models
  -> build directional search polygon
  -> fetch OSMnx road graph
  -> generate pickup candidates
  -> merge nearby duplicate-ish candidates
  -> resolve pricing provider
  -> run KD-tree budgeted search
  -> price original pickup
  -> return final result event with ranked pickup options
```

The search endpoint streams newline-delimited JSON events so the UI can show progress while the backend is working.

## Project Layout

```text
src/farewalk/
  main.py              FastAPI app creation and static frontend serving
  config.py            Pydantic settings loaded from .env
  api/
    routes.py          HTTP routes and streamed response shaping
  schemas/
    search.py          Public search request/response schemas
    roads.py           Public road graph request/response schemas
  models/
    geo.py             Internal LatLng dataclass
    road.py            Internal candidate/result dataclasses
  services/
    trip_search.py     End-to-end search orchestration
    roads.py           OSMnx road graph fetching
    candidates.py      Candidate generation and dedupe
    search.py          KD-tree budgeted search algorithm
    pricing.py         Pricing provider registry and Uber/stub providers
  utils/
    geo.py             Search polygon and interpolation geometry
    projections.py     Local projected CRS helpers
    spatial.py         KD-tree and spatial neighbor helpers
  static/
    index.html         Browser UI
```

## Entry Point

[main.py](/Users/denzyld/Desktop/i/Side_Projects/farewalk/src/farewalk/main.py) creates the FastAPI app:

```python
app = FastAPI(title=settings.app_name)
app.include_router(router)
app.mount("/static", StaticFiles(directory=static_dir), name="static")
```

It also serves `/` by returning `src/farewalk/static/index.html`.

## API Endpoints

`GET /health`

Returns:

```json
{"status": "ok"}
```

`GET /config/defaults`

Returns the effective backend defaults used by the frontend:

```json
{
  "network_type": "drive",
  "radius_m": 1000.0,
  "half_angle_deg": 90.0,
  "local_circle_radius_m": 500.0,
  "arc_steps": 24,
  "road_point_spacing_m": 100.0,
  "candidate_merge_radius_m": 20.0,
  "budget": 100,
  "walk_penalty": 0.001,
  "max_leaf_size": 12,
  "pricing_provider": "auto",
  "pricing_mode": "uber"
}
```

`POST /roads/trip-graph`

Builds the same search polygon and returns road graph size:

```json
{
  "node_count": 123,
  "edge_count": 456
}
```

`POST /search/trip/stream`

Main search endpoint. It streams NDJSON events such as:

```json
{"type":"stage","stage":"road_graph","message":"Fetching OpenStreetMap road graph"}
{"type":"road_graph","nodes":123,"edges":456}
{"type":"candidates","count":88}
{"type":"zones","zones":[...]}
{"type":"sample","phase":"representative","price":24.50,"score":25.12}
{"type":"result","result":{...},"metadata":{...}}
```

The final `result` contains the best pickup as top-level fields plus ranked alternatives:

```json
{
  "pickup_lat": -37.81,
  "pickup_lng": 144.96,
  "price": 35.25,
  "original_price": 42.10,
  "walk_distance_m": 180.0,
  "score": 35.43,
  "savings": 6.85,
  "options": [
    {
      "pickup_lat": -37.81,
      "pickup_lng": 144.96,
      "price": 35.25,
      "walk_distance_m": 180.0,
      "score": 35.43,
      "savings": 6.85
    }
  ],
  "search_area_geojson": {}
}
```

## Request Settings

The search request accepts:

```json
{
  "origin_lat": -37.81,
  "origin_lng": 144.96,
  "destination_lat": -37.91,
  "destination_lng": 145.13,
  "radius_m": 1000,
  "half_angle_deg": 90,
  "local_circle_radius_m": 500,
  "arc_steps": 24,
  "network_type": "drive",
  "road_point_spacing_m": 100,
  "candidate_merge_radius_m": 20,
  "budget": 100,
  "walk_penalty": 0.001,
  "max_leaf_size": 12,
  "pricing_provider": "auto"
}
```

Meaning:

- `radius_m`: forward directional search distance.
- `half_angle_deg`: half-width of the directional wedge.
- `local_circle_radius_m`: circular search area around the origin.
- `arc_steps`: polygon arc resolution.
- `network_type`: OSMnx road network type, usually `drive`.
- `road_point_spacing_m`: spacing for interpolated edge candidates.
- `candidate_merge_radius_m`: projected-meter dedupe radius for nearby candidates.
- `budget`: max number of price calls during search.
- `walk_penalty`: score penalty per meter walked.
- `max_leaf_size`: max candidate count per KD-tree leaf zone.
- `pricing_provider`: `auto`, `stub`, or `uber`.

## Configuration

[config.py](/Users/denzyld/Desktop/i/Side_Projects/farewalk/src/farewalk/config.py) defines defaults. `.env` overrides those values at runtime.

Current built-in defaults:

```text
DEFAULT_NETWORK_TYPE=drive
DEFAULT_SEARCH_RADIUS_M=1000
DEFAULT_HALF_ANGLE_DEG=90
DEFAULT_LOCAL_CIRCLE_RADIUS_M=500
DEFAULT_ARC_STEPS=24
DEFAULT_ROAD_POINT_SPACING_M=100
DEFAULT_CANDIDATE_MERGE_RADIUS_M=20
DEFAULT_SEARCH_BUDGET=100
DEFAULT_WALK_PENALTY_LAMBDA=0.001
DEFAULT_MAX_LEAF_SIZE=12
DEFAULT_PRICING_PROVIDER=auto
UBER_PRODUCT=UBERX
```

For local changes, edit `.env`, not `config.py`.

## Geometry

Geographic coordinates arrive as WGS84 latitude/longitude.

For meter-based geometry, the app projects coordinates into a local UTM CRS using [projections.py](/Users/denzyld/Desktop/i/Side_Projects/farewalk/src/farewalk/utils/projections.py).

This matters because raw lat/lng degrees are not meters. Distance calculations, polygon buffers, candidate merging, and KD-tree splitting need projected meter coordinates.

[geo.py](/Users/denzyld/Desktop/i/Side_Projects/farewalk/src/farewalk/utils/geo.py) builds the search polygon:

```text
origin circle + directional wedge toward destination
```

The polygon is then converted back to WGS84 for OSMnx and frontend display.

## Road Graph

[roads.py](/Users/denzyld/Desktop/i/Side_Projects/farewalk/src/farewalk/services/roads.py) calls OSMnx:

```python
ox.graph_from_polygon(search_polygon, network_type=network_type)
```

OSMnx fetches road data from OpenStreetMap/Overpass. This can be slow and may create a local `cache/` directory.

The road graph is not simplified or mutated by farewalk. Candidate cleanup happens after graph fetching.

## Candidate Generation

[candidates.py](/Users/denzyld/Desktop/i/Side_Projects/farewalk/src/farewalk/services/candidates.py) creates pickup candidates from:

- graph nodes
- interpolated road-edge points

Then it deduplicates nearby candidates using projected-meter grid bucketing.

This avoids wasting price calls on multiple OSMnx nodes that represent the same real-world intersection or nearby lane-separated road nodes.

`candidate_merge_radius_m <= 0` disables merging.

## Search Algorithm

[search.py](/Users/denzyld/Desktop/i/Side_Projects/farewalk/src/farewalk/services/search.py) performs a budgeted KD-tree search.

High-level flow:

```text
project candidates into meters
build KD-tree
collect leaf zones
phase 1: price one representative candidate per zone
phase 2: refine promising zones until budget is used
return best sampled candidate plus top 7 sampled candidates
```

Zone refinement priority balances:

- exploit: zones with low known scores
- explore: zones with fewer samples
- gradient: zones near cheap neighboring zones

The ranking is by score, not raw price.

If `walk_penalty = 0`, the score is effectively price-only.

## Pricing Providers

[pricing.py](/Users/denzyld/Desktop/i/Side_Projects/farewalk/src/farewalk/services/pricing.py) defines provider selection.

Providers:

- `stub`: deterministic fake pricing for tests/dev.
- `uber`: live Uber pricing using a cookie and reverse-engineered mobile GraphQL request.
- `auto`: uses Uber if `UBER_COOKIE` is configured, otherwise stub.

Provider failures are normalized into explicit exception types:

- `PricingConfigurationError`
- `PricingTimeoutError`
- `PricingAuthError`
- `PricingUnavailableError`
- `PricingResponseError`

Do not commit cookies. Store `UBER_COOKIE` in `.env`.

## Search Orchestration

[trip_search.py](/Users/denzyld/Desktop/i/Side_Projects/farewalk/src/farewalk/services/trip_search.py) coordinates one complete backend search.

It owns:

- `search_id`
- stage timings
- road graph fetch
- candidate generation
- provider resolution
- search execution
- original pickup pricing
- structured provider error events
- final execution metadata

The API route layer stays thin and only adapts this execution result into streamed NDJSON.

## Streaming

The stream route uses:

- `Queue`
- background `Thread`
- `StreamingResponse`
- newline-delimited JSON

The worker thread runs the actual search and pushes events into the queue. The response generator yields one JSON line at a time until the worker emits a done sentinel.

This keeps the browser updated while OSMnx and pricing calls are running.

## Tests

Run unit tests:

```bash
make test_unit
```

Run integration tests:

```bash
make test_integration
```

Run everything:

```bash
make test_all
```

Raw equivalents:

```bash
pytest tests/ -v --ignore=tests/integration
pytest tests/integration -v
```

Test split:

- `tests/test_geo.py`: search polygon and geometry helpers.
- `tests/test_projections.py`: UTM/projection behavior.
- `tests/test_spatial.py`: KD-tree and neighbor logic.
- `tests/test_candidates.py`: road candidate generation and dedupe.
- `tests/test_search.py`: scoring and KD-tree search behavior.
- `tests/test_pricing.py`: provider registry and Uber failure handling.
- `tests/test_routes.py`: trip-search orchestration with mocked dependencies.
- `tests/test_schemas.py`: request validation.
- `tests/integration/test_api.py`: streamed API smoke tests with mocked backend pipeline.
- `tests/integration/test_uber_pricing.py`: live Uber smoke tests, skipped unless `UBER_COOKIE` is set.

## Run Locally

Install:

```bash
pip install -e .
```

Start:

```bash
uvicorn farewalk.main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

Debug slow imports:

```bash
python -X importtime -m uvicorn farewalk.main:app --log-level debug --reload
```

## Phone Access For Personal Use

The recommended personal setup is:

```text
phone browser -> Tailscale -> laptop running farewalk
```

This avoids deployment and avoids exposing a public tunnel.

Steps:

1. Install Tailscale on the laptop and phone.
2. Log into the same Tailscale account on both.
3. Keep the laptop plugged in and awake while plugged in:

```bash
sudo pmset -c sleep 0
sudo pmset -c displaysleep 10
sudo pmset -c disksleep 10
sudo pmset -c womp 1
```

4. Enable SSH:

```bash
sudo systemsetup -setremotelogin on
```

5. Get the laptop Tailscale IP:

```bash
tailscale ip -4
```

6. Start farewalk remotely over SSH:

```bash
cd /Users/denzyld/Desktop/i/Side_Projects/farewalk && nohup .venv/bin/uvicorn farewalk.main:app --host 0.0.0.0 --port 8000 > /tmp/farewalk.log 2>&1 &
```

7. Open on phone:

```text
http://<laptop-tailscale-ip>:8000
```

8. Stop farewalk:

```bash
pkill -f "uvicorn farewalk.main:app"
```

The laptop must be awake and connected. It can be locked; it does not need to be left unlocked.

## Learning Order

If you want to understand the backend from scratch, read in this order:

1. [main.py](/Users/denzyld/Desktop/i/Side_Projects/farewalk/src/farewalk/main.py)
2. [config.py](/Users/denzyld/Desktop/i/Side_Projects/farewalk/src/farewalk/config.py)
3. [schemas/search.py](/Users/denzyld/Desktop/i/Side_Projects/farewalk/src/farewalk/schemas/search.py)
4. [api/routes.py](/Users/denzyld/Desktop/i/Side_Projects/farewalk/src/farewalk/api/routes.py)
5. [services/trip_search.py](/Users/denzyld/Desktop/i/Side_Projects/farewalk/src/farewalk/services/trip_search.py)
6. [utils/projections.py](/Users/denzyld/Desktop/i/Side_Projects/farewalk/src/farewalk/utils/projections.py)
7. [utils/geo.py](/Users/denzyld/Desktop/i/Side_Projects/farewalk/src/farewalk/utils/geo.py)
8. [services/roads.py](/Users/denzyld/Desktop/i/Side_Projects/farewalk/src/farewalk/services/roads.py)
9. [services/candidates.py](/Users/denzyld/Desktop/i/Side_Projects/farewalk/src/farewalk/services/candidates.py)
10. [utils/spatial.py](/Users/denzyld/Desktop/i/Side_Projects/farewalk/src/farewalk/utils/spatial.py)
11. [services/search.py](/Users/denzyld/Desktop/i/Side_Projects/farewalk/src/farewalk/services/search.py)
12. [services/pricing.py](/Users/denzyld/Desktop/i/Side_Projects/farewalk/src/farewalk/services/pricing.py)
13. `tests/`

Suggested loop:

```text
read one module -> explain what it owns -> run related tests -> trace one request through it
```

## Current Limitations

- Walking distance is Euclidean projected distance, not road-network walking distance.
- Search result quality depends on budget, candidate spacing, merge radius, and provider stability.
- Uber pricing depends on a browser/session cookie and can break if Uber changes its internal API.
- OSMnx/Overpass calls can be slow or rate limited.
- No database or persistent job queue exists.
- The app is intended as a personal local tool, not a deployed public service.
