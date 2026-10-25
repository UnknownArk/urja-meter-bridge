# Urja Meter Bridge — Flock Energy API & Telemetry Service

A clean, documented, and resilient REST API service built over the legacy **Urja Meter Ops** portal (`https://urja-ops.flockenergy.tech`).

This service eliminates manual copy-pasting for product and data teams by providing programmatic, structured access to smart-meter specifications, grid hierarchy topology, and normalized 7-day consumption telemetry.

---

## Quick Links
* **Interactive Operations Console:** `http://localhost:8000/` (or `http://localhost:8000/dashboard`)
* **Protocol & Reverse-Engineering Analysis:** [PROTOCOL.md](PROTOCOL.md)
* **Self-Critique & Reflection:** [REFLECTION.md](REFLECTION.md)
* **OpenAPI 3.1 Specification:** [openapi.json](openapi.json)
* **Interactive Documentation (when running):** `http://localhost:8000/docs` (Swagger UI) or `/redoc`

---

## Architecture & Project Structure

The project is intentionally lean and appropriately sized (under 350 lines of application logic):

```
urja-meter-bridge/
├── client.py        # Upstream HTTP adapter (session lifecycle, CSRF headers, auto-relogin, HMAC bulk sync)
├── models.py        # Pydantic schemas (data normalization, empty string cleanup, ISO-8601 UTC dates, floats)
├── main.py          # FastAPI application (in-memory index, search/filter engine, topology builder, REST routes)
├── dashboard.html   # Zero-dependency ops console (CDN Leaflet Jaipur grid map + Chart.js 337-interval telemetry)
├── requirements.txt # Project dependencies (fastapi, uvicorn, httpx, pydantic)
├── PROTOCOL.md      # In-depth technical report of the Urja portal protocol & data quirks
├── REFLECTION.md    # Transparent answers to the 5 evaluation reflection questions
├── openapi.json     # Validated OpenAPI 3.1 specification
├── tests/           # Unit & resilience test suite (fully mocked offline fixtures)
└── README.md        # Front door documentation & instructions
```

### Request Flow
```
Downstream Client (App / Engineer)
       │
       ▼
 FastAPI Service (Port 8000)
       ├── In-Memory Catalog (Sub-millisecond Search, Filtering, Grid Hierarchy)
       └── On-Demand Telemetry Proxy (Type & Timestamp Normalization)
             │
             ▼
 UrjaClient (Session Pool)
       │ (Auto-relogin on 401, SvelteKit CSRF headers)
       ▼
 Legacy Urja Portal (https://urja-ops.flockenergy.tech)
```

---

## Getting Started

### Prerequisites
* Python 3.10+ (tested on Python 3.14)
* Virtual environment (recommended)

### 1. Installation
Clone the repository and install dependencies:
```bash
git clone https://github.com/UnknownArk/urja-meter-bridge.git
cd urja-meter-bridge
pip install -r requirements.txt
```

### 2. Running the API Service
Start the service with `uvicorn`:
```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
*(Alternatively, if your Python Scripts folder is in your system PATH: `uvicorn main:app --reload`)*

On startup, the service will:
1. Authenticate against `https://urja-ops.flockenergy.tech` using operator credentials.
2. Synchronize and sanitize all 403 meters into an indexed in-memory catalog.
3. Serve the API at `http://localhost:8000`. Opening `http://localhost:8000` in your web browser automatically opens the operations console, while API clients receive the JSON discovery payload.

### 3. Running Tests
Run the offline unit and resilience test suite (runs 100% offline with zero network dependencies in ~1s):
```bash
python -m pytest
```

---

## API Endpoints & Sample Requests

### 1. Search & Filter Meters
`GET /api/v1/meters`
Supports query filtering (`?q=...`), installation status (`?status=Installed`), manufacturer (`?make=Genus`), and transformer code (`?dt=DT-001`).

```bash
curl -X GET "http://localhost:8000/api/v1/meters?q=Genus&status=Installed&page=1&limit=2"
```

**Response (HTTP 200 OK):**
```json
{
  "total": 49,
  "page": 1,
  "limit": 2,
  "total_pages": 25,
  "data": [
    {
      "meter_id": "J100003",
      "serial_no": "L&84997",
      "make": "Genus",
      "phase_type": "single",
      "install_status": "Installed",
      "dt_code": "DT-004",
      "dt_name": "Raja Park DT 4"
    },
    {
      "meter_id": "J100008",
      "serial_no": "SE63900",
      "make": "Genus",
      "phase_type": "single",
      "install_status": "Installed",
      "dt_code": "DT-009",
      "dt_name": "Sikar Road DT 9"
    }
  ]
}
```

---

### 2. Single Meter Details & Network Position
`GET /api/v1/meters/{meter_id}`

```bash
curl -X GET "http://localhost:8000/api/v1/meters/J100000"
```

**Response (HTTP 200 OK):**
```json
{
  "meter_id": "J100000",
  "serial_no": "SE33962",
  "make": "HPL",
  "phase_type": "single",
  "install_status": "Decommissioned",
  "install_type": "Whole Current",
  "build": "legacy",
  "dt_code": "DT-001",
  "dt_name": "Malviya Nagar DT 1",
  "hierarchy": {
    "zone": {
      "name": "Jaipur Zone 1",
      "code": "Z-01"
    },
    "circle": {
      "name": "Circle 1",
      "code": "C-01"
    },
    "division": {
      "name": "Division 1",
      "code": "D-01"
    },
    "subdivision": {
      "name": "Subdivision 1",
      "code": "SD-01"
    },
    "substation": {
      "name": "Substation 1",
      "code": "SS-01"
    },
    "feeder": {
      "name": "Feeder 1",
      "code": "F-001"
    },
    "dt": {
      "name": "Malviya Nagar DT 1",
      "code": "DT-001"
    }
  },
  "geo": {
    "latitude": 26.938961002479868,
    "longitude": 75.83095696146852
  }
}
```

---

### 3. Consumption Telemetry
`GET /api/v1/meters/{meter_id}/consumption`

Converts raw string floats into typed numbers and non-standard timestamps (`23/06/2026 23:30`) into standard ISO-8601 UTC datetimes.

```bash
curl -X GET "http://localhost:8000/api/v1/meters/J100000/consumption"
```

**Response (HTTP 200 OK):**
```json
{
  "meter_id": "J100000",
  "readings_count": 337,
  "readings": [
    {
      "timestamp": "2026-06-23T18:00:00Z",
      "kwh": 48438.74,
      "kvah": 52313.84,
      "volt_r": 226.0
    },
    {
      "timestamp": "2026-06-23T18:30:00Z",
      "kwh": 48439.16,
      "kvah": 52314.29,
      "volt_r": 229.0
    }
  ]
}
```

---

### 4. Reconstructed Network Hierarchy Tree
`GET /api/v1/hierarchy`

Returns the utility's grid hierarchy tree grouped by `Zone -> Circle -> Feeder -> DT -> [Meters]`.

```bash
curl -X GET "http://localhost:8000/api/v1/hierarchy"
```

---

### 5. Distribution Transformers Directory
`GET /api/v1/transformers`

Retrieves all 40 distribution transformers with mapped feeder codes, official capacities in kVA (ingested from `/portal/dts`), and accurate connected meter counts.

```bash
curl -X GET "http://localhost:8000/api/v1/transformers"
```

**Response Sample (HTTP 200 OK):**
```json
[
  {
    "code": "DT-001",
    "name": "Malviya Nagar DT 1",
    "feeder_code": "F-001",
    "capacity_kva": 100,
    "meter_count": 10
  },
  {
    "code": "DT-002",
    "name": "Vaishali DT 2",
    "feeder_code": "F-004",
    "capacity_kva": 250,
    "meter_count": 10
  }
]
```

---

### 6. Verification Console & Ops Dashboard
`GET /dashboard`

A single, zero-dependency, self-contained operations console served directly by FastAPI:
* **Zero build steps & zero npm dependencies:** Built with pure HTML5, vanilla JS, and lightweight CDNs.
* **Jaipur Grid Map:** Uses CDN Leaflet to display the exact geographic coordinates of smart meters across Jaipur.
* **337-Interval Telemetry Chart:** Uses CDN Chart.js to render dual-axis active energy (kWh) and voltage (V) curves over the 7-day period.
* **Ops Workflow:** Filter by installation status, make, or DT, and inspect full nameplate specifications and electrical hierarchy in real time.

Open in any browser: `http://localhost:8000/` (or `http://localhost:8000/dashboard`)

---

### 7. Health Check
`GET /health`

```bash
curl -X GET "http://localhost:8000/health"
```

**Response (HTTP 200 OK):**
```json
{
  "status": "healthy",
  "indexed_meters": 403,
  "upstream_portal": "https://urja-ops.flockenergy.tech",
  "cache_fresh": true
}
```

---

## Design Decisions & Trade-Offs

1. **In-Memory Catalog vs. Database Storage:**
   * *Decision:* Store the 403 meter records in memory with hash-map indexes on startup rather than requiring SQLite/PostgreSQL.
   * *Trade-off:* Eliminates infrastructure overhead and delivers sub-millisecond search latency. At a scale of ~50,000+ meters, this approach would struggle with memory and server restart time, at which point an external indexed database (PostgreSQL with GiST/pg_trgm indexes) would be necessary.
2. **Bulk Ingestion with Fallback vs. Repeated Upstream Calls:**
   * *Decision:* Implemented a fast bulk ingestion handshake via `/portal/export` on startup, with automatic fallback to `/portal/meters/search` and `/portal/dts`.
   * *Trade-off:* Prevents hammering the utility's server with 400+ HTTP requests on user queries while guaranteeing high availability if the signed export route is deprecated.
3. **Data Sanitization at Ingestion:**
   * *Decision:* Normalized empty strings (`""`) to `null`, resolved the `DT-007` naming conflict (`Sanganer DT 7` vs `Old Malviya Nagar Xfmr`), ingested DT transformer capacities (`capacityKva`), and converted timestamps to timezone-aware UTC.
   * *Trade-off:* Upstream dirty data is cleaned before downstream clients ever consume it, guaranteeing schema predictability.

---

## What Was Intentionally Skipped & Why

1. **Write/Mutation Endpoints:** The assignment explicitly stated that the portal is read-only. No meter creation or update routes were added.
2. **External Caching Systems (Redis):** For a utility dataset of 403 meters, adding Redis or Memcached would be blatant over-engineering. An in-memory dict with TTL handles this scale with zero external dependencies.
3. **Heavy Frontend Frameworks (React/Next.js/Vite):** Rather than bloat the repository with heavy `node_modules`, npm build pipelines, or framework overhead for an ops inspection dashboard, implemented a clean, zero-dependency HTML/JS single-page verification console served directly at `/dashboard` using lightweight CDN Leaflet and Chart.js.

---

## What I Would Improve With More Time

* **Externalized Config (`.env`):** Move credentials and URLs into environment variables with `pydantic-settings` to avoid code defaults.
* **Background Periodic Refresh:** Run an async background task every 30 minutes to re-sync the meter catalog automatically without server restarts.
* **Consumption Date Filtering:** Add query filters (`?from=` and `?to=`) on the `/consumption` endpoint so analysts can fetch specific time slices.
