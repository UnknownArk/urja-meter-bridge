from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


def clean_str(val: Optional[str]) -> Optional[str]:
    """Normalize empty or whitespace-only strings to None."""
    if val is None:
        return None
    val_stripped = str(val).strip()
    return val_stripped if val_stripped else None


class GeoCoordinates(BaseModel):
    latitude: float
    longitude: float


class HierarchyNode(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None

    @field_validator("name", "code", mode="before")
    @classmethod
    def clean_empty_strings(cls, v: Any) -> Optional[str]:
        return clean_str(v)


class MeterHierarchy(BaseModel):
    zone: HierarchyNode
    circle: HierarchyNode
    division: HierarchyNode
    subdivision: HierarchyNode
    substation: HierarchyNode
    feeder: HierarchyNode
    dt: HierarchyNode


class MeterDetail(BaseModel):
    meter_id: str = Field(..., description="Unique meter identifier, e.g. J100000")
    serial_no: str = Field(..., description="Physical serial number from nameplate")
    make: str = Field(..., description="Manufacturer, e.g. HPL, Genus, Secure, L&T, Allied")
    phase_type: str = Field(..., description="Phase rating: 'single' or 'three'")
    install_status: str = Field(..., description="Status: 'Installed', 'Faulty', 'Decommissioned'")
    install_type: str = Field(..., description="Measurement type: 'Whole Current', 'CT Operated'")
    build: Optional[str] = Field(None, description="Hardware release revision (e.g. 'legacy', 'v2')")
    dt_code: str = Field(..., description="Associated distribution transformer code")
    dt_name: Optional[str] = Field(None, description="Resolved distribution transformer name")
    hierarchy: MeterHierarchy
    geo: GeoCoordinates


class MeterSummary(BaseModel):
    meter_id: str
    serial_no: str
    make: str
    phase_type: str
    install_status: str
    dt_code: str
    dt_name: Optional[str] = None


class PaginatedMetersResponse(BaseModel):
    total: int
    page: int
    limit: int
    total_pages: int
    data: List[MeterSummary]


class EnergyReading(BaseModel):
    timestamp: datetime = Field(..., description="Interval end timestamp in ISO-8601 UTC")
    kwh: float = Field(..., description="Cumulative active energy reading (kWh)")
    kvah: float = Field(..., description="Cumulative apparent energy reading (kVAh)")
    volt_r: float = Field(..., description="Red phase voltage (V)")


class ConsumptionResponse(BaseModel):
    meter_id: str
    readings_count: int
    readings: List[EnergyReading]


class Transformer(BaseModel):
    code: str
    name: str
    feeder_code: Optional[str] = None
    capacity_kva: Optional[int] = None
    meter_count: int = 0


class HealthResponse(BaseModel):
    status: str
    indexed_meters: int
    upstream_portal: str
    cache_fresh: bool
