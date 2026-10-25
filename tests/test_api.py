from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

import main
from main import app, sync_registry, METERS_REGISTRY, DT_REGISTRY, normalize_meter_payload

# Deterministic test dataset mirroring the Urja portal structure
MOCK_BULK_METERS = [
    {
        "meterId": "J100000",
        "serialNo": "SE33962",
        "make": "HPL",
        "phaseType": "single",
        "installStatus": "Decommissioned",
        "installType": "Whole Current",
        "build": "legacy",
        "dtCode": "DT-001",
        "hierarchy": {
            "zone": {"name": "Jaipur Zone 1", "code": "Z-01"},
            "circle": {"name": "Circle 1", "code": "C-01"},
            "division": {"name": "Division 1", "code": "D-01"},
            "subdivision": {"name": "Subdivision 1", "code": "SD-01"},
            "substation": {"name": "Substation 1", "code": "SS-01"},
            "feeder": {"name": "Feeder 1", "code": "F-001"},
            "dt": {"name": "Malviya Nagar DT 1", "code": "DT-001"},
        },
        "geo": {"lat": "26.938961", "lng": "75.830956"},
    },
    {
        "meterId": "J100001",
        "serialNo": "SE33963",
        "make": "Secure",
        "phaseType": "single",
        "installStatus": "Installed",
        "installType": "Whole Current",
        "build": "legacy",
        "dtCode": "DT-001",
        "hierarchy": {
            "zone": {"name": "Jaipur Zone 1", "code": "Z-01"},
            "circle": {"name": "Circle 1", "code": "C-01"},
            "division": {"name": "Division 1", "code": "D-01"},
            "subdivision": {"name": "Subdivision 1", "code": "SD-01"},
            "substation": {"name": "Substation 1", "code": "SS-01"},
            "feeder": {"name": "Feeder 1", "code": "F-001"},
            "dt": {"name": "Malviya Nagar DT 1", "code": "DT-001"},
        },
        "geo": {"lat": "26.938970", "lng": "75.830960"},
    },
    {
        "meterId": "J100002",
        "serialNo": "GE12345",
        "make": "Genus",
        "phaseType": "three",
        "installStatus": "Installed",
        "installType": "Whole Current",
        "build": "v2",
        "dtCode": "DT-001",
        "hierarchy": {
            "zone": {"name": "Jaipur Zone 1", "code": "Z-01"},
            "circle": {"name": "Circle 1", "code": "C-01"},
            "division": {"name": "Division 1", "code": "D-01"},
            "subdivision": {"name": "Subdivision 1", "code": "SD-01"},
            "substation": {"name": "Substation 1", "code": "SS-01"},
            "feeder": {"name": "Feeder 1", "code": "F-001"},
            "dt": {"name": "Malviya Nagar DT 1", "code": "DT-001"},
        },
        "geo": {"lat": "26.938980", "lng": "75.830970"},
    },
    {
        "meterId": "J100003",
        "serialNo": "L&84997",
        "make": "Genus",
        "phaseType": "single",
        "installStatus": "Installed",
        "installType": "Whole Current",
        "build": "v2",
        "dtCode": "DT-004",
        "hierarchy": {
            "zone": {"name": "Jaipur Zone 1", "code": "Z-01"},
            "circle": {"name": "Circle 1", "code": "C-01"},
            "division": {"name": "Division 1", "code": "D-01"},
            "subdivision": {"name": "Subdivision 1", "code": "SD-01"},
            "substation": {"name": "Substation 1", "code": "SS-01"},
            "feeder": {"name": "Feeder 2", "code": "F-002"},
            "dt": {"name": "Raja Park DT 4", "code": "DT-004"},
        },
        "geo": {"lat": "26.890000", "lng": "75.820000"},
    },
    {
        "meterId": "J100008",
        "serialNo": "SE63900",
        "make": "Genus",
        "phaseType": "single",
        "installStatus": "Faulty",
        "installType": "Whole Current",
        "build": "legacy",
        "dtCode": "DT-009",
        "hierarchy": {
            "zone": {"name": "Jaipur Zone 2", "code": "Z-02"},
            "circle": {"name": "Circle 2", "code": "C-02"},
            "division": {"name": "Division 2", "code": "D-02"},
            "subdivision": {"name": "Subdivision 2", "code": "SD-02"},
            "substation": {"name": "Substation 2", "code": "SS-02"},
            "feeder": {"name": "Feeder 3", "code": "F-003"},
            "dt": {"name": "Sikar Road DT 9", "code": "DT-009"},
        },
        "geo": {"lat": "26.980000", "lng": "75.770000"},
    },
    {
        "meterId": "J100011",
        "serialNo": "AL99001",
        "make": "Allied",
        "phaseType": "single",
        "installStatus": "Installed",
        "installType": "Whole Current",
        "build": None,
        "dtCode": "DT-002",
        "hierarchy": {
            "zone": {"name": "Jaipur Zone 2", "code": "Z-02"},
            "circle": {"name": "Circle 6", "code": ""},  # empty string code anomaly
            "division": {"name": "Division 3", "code": "D-03"},
            "subdivision": {"name": "Subdivision 3", "code": "SD-03"},
            "substation": {"name": "Substation 3", "code": "SS-03"},
            "feeder": {"name": "Feeder 4", "code": "F-004"},
            "dt": {"name": "Vaishali DT 2", "code": "DT-002"},
        },
        "geo": {"lat": "26.910000", "lng": "75.740000"},
    },
    {
        "meterId": "J100218",
        "serialNo": "LT55441",
        "make": "L&T",
        "phaseType": "three",
        "installStatus": "Installed",
        "installType": "CT Operated",
        "build": "v3",
        "dtCode": "DT-003",
        "hierarchy": {
            "zone": {"name": "Jaipur Zone 1", "code": "Z-01"},
            "circle": {"name": "", "code": "C-01"},  # empty string name anomaly
            "division": {"name": "Division 1", "code": "D-01"},
            "subdivision": {"name": "Subdivision 1", "code": "SD-01"},
            "substation": {"name": "Substation 1", "code": "SS-01"},
            "feeder": {"name": "Feeder 1", "code": "F-001"},
            "dt": {"name": "Mansarovar DT 3", "code": "DT-003"},
        },
        "geo": {"lat": "26.860000", "lng": "75.760000"},
    },
]

MOCK_DTS = [
    {"code": "DT-001", "name": "Malviya Nagar DT 1", "feederCode": "F-001", "capacityKva": 100},
    {"code": "DT-002", "name": "Vaishali DT 2", "feederCode": "F-004", "capacityKva": 250},
    {"code": "DT-003", "name": "Mansarovar DT 3", "feederCode": "F-001", "capacityKva": 160},
    {"code": "DT-004", "name": "Raja Park DT 4", "feederCode": "F-002", "capacityKva": 100},
    {"code": "DT-009", "name": "Sikar Road DT 9", "feederCode": "F-003", "capacityKva": 400},
]

MOCK_ENERGY_READINGS = [
    {
        "timestamp": "23/06/2026 23:30",
        "kwh": "48438.74",
        "kvah": "52313.84",
        "voltR": "226.0",
    },
    {
        "timestamp": "24/06/2026 00:00",
        "kwh": "48439.16",
        "kvah": "52314.29",
        "voltR": "229.0",
    },
]


@pytest.fixture(scope="session")
def client():
    """TestClient fixture with all upstream Urja portal network calls mocked."""
    with patch.object(main.client, "login", return_value=True), \
         patch.object(main.client, "fetch_bulk_export", return_value=MOCK_BULK_METERS), \
         patch.object(main.client, "fetch_dts_paged", return_value={"data": MOCK_DTS, "total": len(MOCK_DTS), "pageSize": 20}), \
         patch.object(main.client, "fetch_energy", return_value=MOCK_ENERGY_READINGS):
        with TestClient(app) as test_client:
            yield test_client


def test_root_discovery(client):
    res = client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert data["service"] == "Flock Energy — Urja Meter Ops API"
    assert "/dashboard" in data["dashboard"]
    assert "meters" in data["endpoints"]
    assert "transformers" in data["endpoints"]


def test_root_browser_redirect(client):
    res = client.get("/", headers={"accept": "text/html,application/xhtml+xml"}, follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "/dashboard"


def test_dashboard_endpoint(client):
    res = client.get("/dashboard")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "leaflet" in res.text.lower()
    assert "chart.js" in res.text.lower()
    assert "Urja Meter Bridge" in res.text


def test_health_endpoint(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["indexed_meters"] == len(MOCK_BULK_METERS)
    assert data["cache_fresh"] is True


def test_list_meters_pagination(client):
    res = client.get("/api/v1/meters?page=1&limit=3")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == len(MOCK_BULK_METERS)
    assert data["page"] == 1
    assert data["limit"] == 3
    assert len(data["data"]) == 3


def test_list_meters_query_filter(client):
    # Search by serial substring
    res = client.get("/api/v1/meters?q=33962")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["data"][0]["meter_id"] == "J100000"

    # Search by make substring
    res = client.get("/api/v1/meters?q=Genus")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3
    for m in data["data"]:
        assert m["make"] == "Genus"


def test_list_meters_status_filter(client):
    res = client.get("/api/v1/meters?status=Installed")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 5
    for m in data["data"]:
        assert m["install_status"] == "Installed"


def test_list_meters_make_filter(client):
    res = client.get("/api/v1/meters?make=Secure")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["data"][0]["meter_id"] == "J100001"


def test_list_meters_dt_filter(client):
    res = client.get("/api/v1/meters?dt=DT-001")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3
    for m in data["data"]:
        assert m["dt_code"] == "DT-001"


def test_list_meters_combined_filters(client):
    res = client.get("/api/v1/meters?make=Genus&status=Installed")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    for m in data["data"]:
        assert m["make"] == "Genus"
        assert m["install_status"] == "Installed"


def test_get_single_meter_success(client):
    res = client.get("/api/v1/meters/J100000")
    assert res.status_code == 200
    data = res.json()
    assert data["meter_id"] == "J100000"
    assert data["serial_no"] == "SE33962"
    assert data["make"] == "HPL"
    assert data["geo"]["latitude"] == pytest.approx(26.938961, rel=1e-5)
    assert data["geo"]["longitude"] == pytest.approx(75.830956, rel=1e-5)
    assert data["hierarchy"]["zone"]["name"] == "Jaipur Zone 1"
    assert data["hierarchy"]["feeder"]["code"] == "F-001"


def test_get_single_meter_sanitization(client):
    # J100011 had empty circle code in raw data ("")
    res = client.get("/api/v1/meters/J100011")
    assert res.status_code == 200
    data = res.json()
    assert data["hierarchy"]["circle"]["code"] is None
    assert data["hierarchy"]["circle"]["name"] == "Circle 6"

    # J100218 had empty circle name in raw data ("")
    res2 = client.get("/api/v1/meters/J100218")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["hierarchy"]["circle"]["name"] is None
    assert data2["hierarchy"]["circle"]["code"] == "C-01"


def test_meter_not_found(client):
    res = client.get("/api/v1/meters/NONEXISTENT_9999")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_meter_consumption_success_and_timezone(client):
    res = client.get("/api/v1/meters/J100000/consumption")
    assert res.status_code == 200
    data = res.json()
    assert data["meter_id"] == "J100000"
    assert data["readings_count"] == 2

    first_reading = data["readings"][0]
    # Check that timestamp is ISO UTC (ends with 'Z' or '+00:00')
    assert first_reading["timestamp"].endswith("Z") or "+00:00" in first_reading["timestamp"]
    # 23:30 IST (UTC+05:30) converted to UTC must be 18:00 UTC
    assert "18:00:00" in first_reading["timestamp"]
    assert first_reading["kwh"] == pytest.approx(48438.74)
    assert first_reading["kvah"] == pytest.approx(52313.84)
    assert first_reading["volt_r"] == pytest.approx(226.0)


def test_meter_consumption_not_found(client):
    res = client.get("/api/v1/meters/NONEXISTENT/consumption")
    assert res.status_code == 404


def test_meter_consumption_upstream_error(client):
    with patch.object(main.client, "fetch_energy", side_effect=RuntimeError("Upstream timeout")):
        res = client.get("/api/v1/meters/J100000/consumption")
        assert res.status_code == 502
        assert "Upstream timeout" in res.json()["detail"]


def test_list_transformers(client):
    res = client.get("/api/v1/transformers")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 5

    dt_map = {dt["code"]: dt for dt in data}
    assert "DT-001" in dt_map
    dt1 = dt_map["DT-001"]
    assert dt1["name"] == "Malviya Nagar DT 1"
    assert dt1["feeder_code"] == "F-001"
    assert dt1["capacity_kva"] == 100
    assert dt1["meter_count"] == 3  # J100000, J100001, J100002

    dt2 = dt_map["DT-002"]
    assert dt2["capacity_kva"] == 250
    assert dt2["meter_count"] == 1  # J100011


def test_hierarchy_endpoint(client):
    res = client.get("/api/v1/hierarchy")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, dict)
    assert "Jaipur Zone 1" in data
    assert "Circle 1" in data["Jaipur Zone 1"]


def test_fallback_sync_resilience(client):
    """Test that when bulk export fails, sync_registry falls back to fetch_meters_paged across all pages without leaking state."""
    fallback_page_1 = {
        "data": [
            {
                "meterId": "J100000",
                "serialNo": "SE33962",
                "make": "HPL",
                "phaseType": "single",
                "installStatus": "Decommissioned",
                "dtCode": "DT-001",
            }
        ],
        "page": 1,
        "pageSize": 1,
        "total": 2,
    }
    fallback_page_2 = {
        "data": [
            {
                "meterId": "J100001",
                "serialNo": "SE33963",
                "make": "Secure",
                "phaseType": "single",
                "installStatus": "Installed",
                "dtCode": "DT-001",
            }
        ],
        "page": 2,
        "pageSize": 1,
        "total": 2,
    }

    def mock_paged_meters(query="", page=1):
        if page == 1:
            return fallback_page_1
        return fallback_page_2

    saved_meters = dict(METERS_REGISTRY)
    saved_dts = dict(DT_REGISTRY)

    try:
        with patch.object(main.client, "fetch_bulk_export", side_effect=RuntimeError("Bulk route down 500")), \
             patch.object(main.client, "fetch_meters_paged", side_effect=mock_paged_meters) as mock_paged, \
             patch.object(main.client, "fetch_dts_paged", return_value={"data": MOCK_DTS, "total": len(MOCK_DTS), "pageSize": 20}):

            sync_registry()

            assert mock_paged.call_count == 2
            assert len(METERS_REGISTRY) == 2
            assert "J100000" in METERS_REGISTRY
            assert "J100001" in METERS_REGISTRY
            assert "DT-001" in DT_REGISTRY
            assert DT_REGISTRY["DT-001"].capacity_kva == 100
            assert DT_REGISTRY["DT-001"].meter_count == 2

            # Verify API endpoints work during fallback state
            res_meters = client.get("/api/v1/meters")
            assert res_meters.status_code == 200
            assert res_meters.json()["total"] == 2

            res_single = client.get("/api/v1/meters/J100000")
            assert res_single.status_code == 200
            assert res_single.json()["dt_name"] == "Malviya Nagar DT 1"
    finally:
        # Prevent test pollution by restoring registry state
        METERS_REGISTRY.clear()
        METERS_REGISTRY.update(saved_meters)
        DT_REGISTRY.clear()
        DT_REGISTRY.update(saved_dts)


def test_normalize_meter_payload_resilience():
    """Verify that normalize_meter_payload safely handles null dicts, missing fields, and alternative keys."""
    # Case 1: Null hierarchy and null geo
    raw1 = {
        "meterId": "J999001",
        "serialNo": "SN-001",
        "hierarchy": None,
        "geo": None,
    }
    m1 = normalize_meter_payload(raw1)
    assert m1.meter_id == "J999001"
    assert m1.geo.latitude == 0.0
    assert m1.geo.longitude == 0.0
    assert m1.hierarchy.zone.name is None

    # Case 2: Null nodes inside hierarchy
    raw2 = {
        "meterId": "J999002",
        "serialNo": "SN-002",
        "hierarchy": {
            "zone": None,
            "circle": {"name": "", "code": None},
            "dt": None,
        },
        "geo": {"latitude": "26.9124", "longitude": "75.7873"},
        "status": "Installed",  # alternative key for installStatus
        "dt": "DT-010",        # alternative key for dtCode
    }
    m2 = normalize_meter_payload(raw2)
    assert m2.meter_id == "J999002"
    assert m2.install_status == "Installed"
    assert m2.dt_code == "DT-010"
    assert m2.geo.latitude == pytest.approx(26.9124)
    assert m2.geo.longitude == pytest.approx(75.7873)


def test_meter_consumption_null_and_empty_coercion(client):
    """Verify that empty strings or None numeric fields in telemetry default to 0.0 without dropping readings."""
    bad_readings = [
        {
            "timestamp": "23/06/2026 23:30",
            "kwh": "",         # empty string
            "kvah": None,      # null
            "voltR": "228.5",
        },
        {
            "timestamp": "24/06/2026 00:00",
            "kwh": "100.5",
            "kvah": "110.0",
            "volt_r": None,    # alternative key with null
        },
        {
            "timestamp": "invalid_date_format",
            "kwh": "10.0",
        },
    ]

    with patch.object(main.client, "fetch_energy", return_value=bad_readings):
        res = client.get("/api/v1/meters/J100000/consumption")
        assert res.status_code == 200
        data = res.json()
        assert data["readings_count"] == 2  # 2 valid timestamps, 1 invalid skipped
        assert data["readings"][0]["kwh"] == 0.0
        assert data["readings"][0]["kvah"] == 0.0
        assert data["readings"][0]["volt_r"] == pytest.approx(228.5)
        assert data["readings"][1]["volt_r"] == 0.0


def test_meter_consumption_empty_upstream_404(client):
    """Verify that if upstream returns 404 for energy readings, API returns 200 with empty list."""
    with patch.object(main.client, "fetch_energy", return_value=[]):
        res = client.get("/api/v1/meters/J100000/consumption")
        assert res.status_code == 200
        data = res.json()
        assert data["readings_count"] == 0
        assert data["readings"] == []


def test_list_meters_query_boundaries(client):
    """Verify pagination and limit boundary validations (422 on invalid ranges)."""
    # page < 1
    res_page0 = client.get("/api/v1/meters?page=0")
    assert res_page0.status_code == 422

    # limit < 1
    res_lim0 = client.get("/api/v1/meters?limit=0")
    assert res_lim0.status_code == 422

    # limit > 100
    res_lim101 = client.get("/api/v1/meters?limit=101")
    assert res_lim101.status_code == 422

    # Whitespace-only search query should be ignored
    res_ws = client.get("/api/v1/meters?q=%20%20%20")
    assert res_ws.status_code == 200
    assert res_ws.json()["total"] == len(MOCK_BULK_METERS)


def test_get_meter_case_and_whitespace_insensitivity(client):
    """Verify meter lookup handles lowercase and whitespace padding."""
    res = client.get("/api/v1/meters/%20j100000%20")
    assert res.status_code == 200
    assert res.json()["meter_id"] == "J100000"


def test_client_fetch_geo_method():
    """Verify UrjaClient.fetch_geo method handles success and 404."""
    from unittest.mock import MagicMock
    test_client = main.client

    # Case 1: 200 OK
    mock_res_200 = MagicMock()
    mock_res_200.status_code = 200
    mock_res_200.json.return_value = {"data": {"latitude": "26.9389", "longitude": "75.8309"}}

    with patch.object(test_client, "_request_with_retry", return_value=mock_res_200):
        geo = test_client.fetch_geo("J100000")
        assert geo == {"latitude": pytest.approx(26.9389), "longitude": pytest.approx(75.8309)}

    # Case 2: 404 Not Found
    mock_res_404 = MagicMock()
    mock_res_404.status_code = 404

    with patch.object(test_client, "_request_with_retry", return_value=mock_res_404):
        geo_404 = test_client.fetch_geo("NONEXISTENT")
        assert geo_404 is None

