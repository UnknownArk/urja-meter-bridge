from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
import math
import os
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse

from client import UrjaClient
from models import (
    ConsumptionResponse,
    EnergyReading,
    GeoCoordinates,
    HealthResponse,
    HierarchyNode,
    MeterDetail,
    MeterHierarchy,
    MeterSummary,
    PaginatedMetersResponse,
    Transformer,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("urja_api")

IST = ZoneInfo("Asia/Kolkata")
DASHBOARD_PATH = os.path.join(os.path.dirname(__file__), "dashboard.html")

client = UrjaClient()

# In-memory registry & indexed lookup tables
METERS_REGISTRY: Dict[str, MeterDetail] = {}
DT_REGISTRY: Dict[str, Transformer] = {}
HIERARCHY_TREE: Dict[str, Any] = {}
LAST_SYNC: Optional[datetime] = None


def to_float(val: Any, default: float = 0.0) -> float:
    """Safely convert any numeric value or string to float, defaulting on None, empty string, or error."""
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def normalize_meter_payload(raw: Dict[str, Any]) -> MeterDetail:
    """Normalize and sanitize raw meter records from the Urja portal."""
    hierarchy_raw = raw.get("hierarchy") or {}

    def extract_node(node_key: str) -> HierarchyNode:
        node_dict = hierarchy_raw.get(node_key) or {}
        return HierarchyNode(
            name=node_dict.get("name"),
            code=node_dict.get("code"),
        )

    zone = extract_node("zone")
    circle = extract_node("circle")
    division = extract_node("division")
    subdivision = extract_node("subdivision")
    substation = extract_node("substation")
    feeder = extract_node("feeder")
    dt = extract_node("dt")

    geo_raw = raw.get("geo") or {}
    lat_val = geo_raw.get("lat") if "lat" in geo_raw else geo_raw.get("latitude")
    lng_val = geo_raw.get("lng") if "lng" in geo_raw else geo_raw.get("longitude")

    geo = GeoCoordinates(
        latitude=to_float(lat_val, 0.0),
        longitude=to_float(lng_val, 0.0),
    )

    dt_code = raw.get("dtCode") or raw.get("dt") or dt.code or "UNKNOWN"
    dt_name = dt.name

    install_status = raw.get("installStatus") or raw.get("status") or "UNKNOWN"

    return MeterDetail(
        meter_id=raw["meterId"],
        serial_no=raw["serialNo"],
        make=raw.get("make") or "UNKNOWN",
        phase_type=raw.get("phaseType") or "single",
        install_status=install_status,
        install_type=raw.get("installType") or "Whole Current",
        build=raw.get("build"),
        dt_code=dt_code,
        dt_name=dt_name,
        hierarchy=MeterHierarchy(
            zone=zone,
            circle=circle,
            division=division,
            subdivision=subdivision,
            substation=substation,
            feeder=feeder,
            dt=dt,
        ),
        geo=geo,
    )


def rebuild_hierarchy_tree() -> None:
    """Build a nested topology tree: Zone -> Circle -> Feeder -> DT -> Meters."""
    global HIERARCHY_TREE
    tree: Dict[str, Any] = {}

    for meter in METERS_REGISTRY.values():
        h = meter.hierarchy
        zone_key = h.zone.name or "Unassigned Zone"
        circle_key = h.circle.name or "Unassigned Circle"
        feeder_key = h.feeder.name or (f"Feeder ({h.feeder.code})" if h.feeder.code else "Unassigned Feeder")
        dt_key = f"{meter.dt_name} ({meter.dt_code})" if meter.dt_name else meter.dt_code

        tree.setdefault(zone_key, {}).setdefault(circle_key, {}).setdefault(feeder_key, {}).setdefault(dt_key, []).append(
            {
                "meter_id": meter.meter_id,
                "serial_no": meter.serial_no,
                "status": meter.install_status,
            }
        )

    HIERARCHY_TREE = tree


def ingest_transformers(dt_counts: Dict[str, int]) -> None:
    """Populate DT_REGISTRY with transformer capacity, feeder, and connected meter counts."""
    global DT_REGISTRY
    dt_registry: Dict[str, Transformer] = {}

    # Initialize from DT counts found in meters
    for dt_code, count in dt_counts.items():
        name = next((m.dt_name for m in METERS_REGISTRY.values() if m.dt_code == dt_code and m.dt_name), dt_code)
        feeder = next(
            (m.hierarchy.feeder.code for m in METERS_REGISTRY.values() if m.dt_code == dt_code and m.hierarchy.feeder.code),
            None,
        )
        dt_registry[dt_code] = Transformer(
            code=dt_code,
            name=name,
            feeder_code=feeder,
            capacity_kva=None,
            meter_count=count,
        )

    # Ingest capacities and metadata from /portal/dts
    try:
        page = 1
        while True:
            dts_res = client.fetch_dts_paged(page=page)
            dt_items = dts_res.get("data", [])
            if not dt_items:
                break
            for dt_item in dt_items:
                code = dt_item.get("code")
                if not code:
                    continue
                if code in dt_registry:
                    dt_registry[code].capacity_kva = dt_item.get("capacityKva")
                    if dt_item.get("feederCode"):
                        dt_registry[code].feeder_code = dt_item.get("feederCode")
                    if dt_item.get("name"):
                        dt_registry[code].name = dt_item.get("name")
                else:
                    dt_registry[code] = Transformer(
                        code=code,
                        name=dt_item.get("name", code),
                        feeder_code=dt_item.get("feederCode"),
                        capacity_kva=dt_item.get("capacityKva"),
                        meter_count=0,
                    )
            page_size = dts_res.get("pageSize", 20) or 20
            total = dts_res.get("total", len(dt_items))
            if page * page_size >= total:
                break
            page += 1
    except Exception as dt_err:
        logger.warning(f"Could not fetch DT capacities from portal: {dt_err}")

    DT_REGISTRY.clear()
    DT_REGISTRY.update(dt_registry)

    # Backfill dt_name and hierarchy node references in METERS_REGISTRY if missing
    for meter in METERS_REGISTRY.values():
        if meter.dt_code in DT_REGISTRY:
            transformer = DT_REGISTRY[meter.dt_code]
            if not meter.dt_name and transformer.name:
                meter.dt_name = transformer.name
            if not meter.hierarchy.dt.name and transformer.name:
                meter.hierarchy.dt.name = transformer.name
            if not meter.hierarchy.dt.code:
                meter.hierarchy.dt.code = transformer.code
            if not meter.hierarchy.feeder.code and transformer.feeder_code:
                meter.hierarchy.feeder.code = transformer.feeder_code


def sync_registry() -> None:
    """Synchronize meter catalog from the portal, preferring bulk export with search fallback."""
    global LAST_SYNC
    logger.info("Synchronizing meter registry from Urja portal...")

    try:
        # Preferred Fast Path: Signed bulk export (1 request)
        raw_meters = client.fetch_bulk_export()
        logger.info(f"Retrieved {len(raw_meters)} meters via bulk export path.")

        new_registry: Dict[str, MeterDetail] = {}
        dt_counts: Dict[str, int] = {}

        for item in raw_meters:
            meter = normalize_meter_payload(item)
            new_registry[meter.meter_id] = meter
            dt_counts[meter.dt_code] = dt_counts.get(meter.dt_code, 0) + 1

        METERS_REGISTRY.clear()
        METERS_REGISTRY.update(new_registry)
        ingest_transformers(dt_counts)
        rebuild_hierarchy_tree()
        LAST_SYNC = datetime.now(timezone.utc)
        logger.info(f"Registry sync complete. Indexed {len(METERS_REGISTRY)} meters across {len(DT_REGISTRY)} DTs.")

    except Exception as e:
        logger.warning(f"Bulk path encountered issue: {e}. Attempting fallback via search endpoint...")
        try:
            page = 1
            total_pages = 1
            new_registry: Dict[str, MeterDetail] = {}
            dt_counts: Dict[str, int] = {}

            while page <= total_pages:
                fallback_res = client.fetch_meters_paged(query="", page=page)
                items = fallback_res.get("data", [])
                total = fallback_res.get("total", 0)
                page_size = fallback_res.get("pageSize", 20) or 20
                total_pages = max(1, math.ceil(total / page_size))

                for item in items:
                    meter = normalize_meter_payload(item)
                    new_registry[meter.meter_id] = meter
                    dt_counts[meter.dt_code] = dt_counts.get(meter.dt_code, 0) + 1

                page += 1

            METERS_REGISTRY.clear()
            METERS_REGISTRY.update(new_registry)
            ingest_transformers(dt_counts)
            rebuild_hierarchy_tree()
            LAST_SYNC = datetime.now(timezone.utc)
            logger.info(f"Fallback sync complete. Indexed {len(METERS_REGISTRY)} meters across {len(DT_REGISTRY)} DTs.")
        except Exception as fallback_err:
            logger.error(f"Fallback sync also failed: {fallback_err}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: authenticate and index catalog
    sync_registry()
    yield
    # Shutdown: clean up client sessions
    client.close()


app = FastAPI(
    title="Flock Energy — Urja Meter Ops API",
    version="1.0.0",
    description=(
        "Clean, documented programmatic REST service providing structured access "
        "to smart-meter specifications, grid hierarchy, and consumption telemetry "
        "from the legacy Urja Meter Ops portal."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["System"])
def root(request: Request):
    """Service discovery endpoint or browser dashboard redirect."""
    accept = request.headers.get("accept", "")
    if "text/html" in accept and "application/json" not in accept:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    return {
        "service": "Flock Energy — Urja Meter Ops API",
        "version": "1.0.0",
        "documentation": "/docs",
        "openapi_schema": "/openapi.json",
        "dashboard": "/dashboard",
        "endpoints": {
            "health": "/health",
            "meters": "/api/v1/meters",
            "hierarchy": "/api/v1/hierarchy",
            "transformers": "/api/v1/transformers",
            "dashboard": "/dashboard",
        },
    }


@app.get("/dashboard", response_class=HTMLResponse, tags=["Console"], include_in_schema=False)
def serve_dashboard():
    """Interactive ops console for visual inspection of meters, grid map, and telemetry."""
    if not os.path.exists(DASHBOARD_PATH):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dashboard file not found.",
        )
    with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/health", response_model=HealthResponse, tags=["System"])
def health_check():
    """Service health and connection status with upstream Urja portal."""
    return HealthResponse(
        status="healthy" if len(METERS_REGISTRY) > 0 else "degraded",
        indexed_meters=len(METERS_REGISTRY),
        upstream_portal=client.base_url,
        cache_fresh=LAST_SYNC is not None,
    )


@app.get("/api/v1/meters", response_model=PaginatedMetersResponse, tags=["Meters"])
def list_meters(
    q: Optional[str] = Query(None, description="Search query matching meter ID, serial number, or make"),
    status: Optional[str] = Query(None, description="Filter by status: Installed, Faulty, Decommissioned"),
    make: Optional[str] = Query(None, description="Filter by manufacturer: HPL, Genus, Secure, L&T, Allied"),
    dt: Optional[str] = Query(None, description="Filter by DT code: e.g. DT-001"),
    page: int = Query(1, ge=1, description="Page index (1-based)"),
    limit: int = Query(20, ge=1, le=100, description="Page size limit"),
):
    """Retrieve a paginated, filterable list of smart meters."""
    q_clean = q.strip().lower() if q and q.strip() else None
    status_clean = status.strip().lower() if status and status.strip() else None
    make_clean = make.strip().lower() if make and make.strip() else None
    dt_clean = dt.strip().lower() if dt and dt.strip() else None

    filtered: List[MeterSummary] = []

    for m in METERS_REGISTRY.values():
        if q_clean:
            if q_clean not in m.meter_id.lower() and q_clean not in m.serial_no.lower() and q_clean not in m.make.lower():
                continue

        if status_clean and m.install_status.lower() != status_clean:
            continue

        if make_clean and m.make.lower() != make_clean:
            continue

        if dt_clean and m.dt_code.lower() != dt_clean:
            continue

        filtered.append(
            MeterSummary(
                meter_id=m.meter_id,
                serial_no=m.serial_no,
                make=m.make,
                phase_type=m.phase_type,
                install_status=m.install_status,
                dt_code=m.dt_code,
                dt_name=m.dt_name,
            )
        )

    total = len(filtered)
    total_pages = max(1, math.ceil(total / limit))
    start_idx = (page - 1) * limit
    paged_items = filtered[start_idx : start_idx + limit]

    return PaginatedMetersResponse(
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
        data=paged_items,
    )


@app.get("/api/v1/meters/{meter_id}", response_model=MeterDetail, tags=["Meters"])
def get_meter(meter_id: str):
    """Retrieve full nameplate specifications, network position, and coordinates for a meter."""
    clean_id = meter_id.strip().upper()
    meter = METERS_REGISTRY.get(clean_id)
    if not meter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meter '{meter_id}' not found in registry.",
        )
    return meter


@app.get(
    "/api/v1/meters/{meter_id}/consumption",
    response_model=ConsumptionResponse,
    tags=["Telemetry"],
)
def get_meter_consumption(meter_id: str):
    """Retrieve recent 7-day 30-minute interval active/apparent energy and voltage readings.

    Timestamps are standardized into ISO-8601 UTC and numeric strings are converted to floats.
    """
    meter_key = meter_id.strip().upper()
    if meter_key not in METERS_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meter '{meter_id}' not found.",
        )

    try:
        raw_readings = client.fetch_energy(meter_key)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to retrieve energy data from legacy portal: {e}",
        )

    cleaned_readings: List[EnergyReading] = []
    for item in raw_readings:
        try:
            raw_ts = item.get("timestamp", "")
            if not raw_ts:
                continue
            try:
                # Raw format: DD/MM/YYYY HH:mm in Indian Standard Time (UTC+05:30)
                dt_naive = datetime.strptime(raw_ts, "%d/%m/%Y %H:%M")
                dt_utc = dt_naive.replace(tzinfo=IST).astimezone(timezone.utc)
            except ValueError:
                dt_parsed = datetime.fromisoformat(raw_ts)
                if dt_parsed.tzinfo is None:
                    dt_utc = dt_parsed.replace(tzinfo=IST).astimezone(timezone.utc)
                else:
                    dt_utc = dt_parsed.astimezone(timezone.utc)

            volt_val = item.get("voltR") if "voltR" in item else item.get("volt_r")

            cleaned_readings.append(
                EnergyReading(
                    timestamp=dt_utc,
                    kwh=to_float(item.get("kwh"), 0.0),
                    kvah=to_float(item.get("kvah"), 0.0),
                    volt_r=to_float(volt_val, 0.0),
                )
            )
        except Exception:
            continue

    return ConsumptionResponse(
        meter_id=meter_key,
        readings_count=len(cleaned_readings),
        readings=cleaned_readings,
    )


@app.get("/api/v1/hierarchy", tags=["Grid Topology"])
def get_network_hierarchy():
    """Retrieve the reconstructed electrical network tree: Zone -> Circle -> Feeder -> DT -> Meters."""
    return HIERARCHY_TREE


@app.get("/api/v1/transformers", response_model=List[Transformer], tags=["Grid Topology"])
def list_transformers():
    """Retrieve distribution transformers (DTs) with connected meter counts."""
    return list(DT_REGISTRY.values())
