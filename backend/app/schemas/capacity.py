"""
Pydantic schemas for capacity settings, team health checks, and CFD snapshots.
"""

from typing import Optional, List, Dict, Any
from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
# Capacity Settings Schemas
# =============================================================================


class CapacitySettingsBase(BaseModel):
    """Base schema for capacity settings."""

    assignee_email: str = Field(..., max_length=255)
    assignee_name: Optional[str] = Field(None, max_length=255)
    hours_per_week: float = Field(default=40.0, ge=0, le=168)  # Max 168h = 24*7
    focus_factor: float = Field(default=0.8, ge=0.0, le=1.0)
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    notes: Optional[str] = Field(None, max_length=500)

    @field_validator("focus_factor")
    @classmethod
    def validate_focus_factor(cls, v):
        """Ensure focus factor is a valid percentage."""
        if v < 0 or v > 1:
            raise ValueError("Focus factor must be between 0 and 1")
        return v


class CapacitySettingsCreate(CapacitySettingsBase):
    """Schema for creating capacity settings."""

    project_id: Optional[int] = None


class CapacitySettingsUpdate(BaseModel):
    """Schema for updating capacity settings."""

    assignee_name: Optional[str] = Field(None, max_length=255)
    hours_per_week: Optional[float] = Field(None, ge=0, le=168)
    focus_factor: Optional[float] = Field(None, ge=0.0, le=1.0)
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    notes: Optional[str] = Field(None, max_length=500)


class CapacitySettingsInDB(CapacitySettingsBase):
    """Schema for capacity settings from database."""

    id: int
    project_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CapacitySettings(CapacitySettingsInDB):
    """Full capacity settings response schema."""

    effective_capacity: Optional[float] = None

    @classmethod
    def from_orm_with_effective(cls, obj):
        """Create instance with calculated effective capacity."""
        data = {
            "id": obj.id,
            "project_id": obj.project_id,
            "assignee_email": obj.assignee_email,
            "assignee_name": obj.assignee_name,
            "hours_per_week": obj.hours_per_week,
            "focus_factor": obj.focus_factor,
            "valid_from": obj.valid_from,
            "valid_to": obj.valid_to,
            "notes": obj.notes,
            "created_at": obj.created_at,
            "updated_at": obj.updated_at,
            "effective_capacity": obj.effective_capacity,
        }
        return cls(**data)


class TeamCapacitySummary(BaseModel):
    """Summary of team capacity for a sprint."""

    total_theoretical_hours: float
    total_effective_hours: float
    average_focus_factor: float
    team_members: int
    capacity_by_member: List[Dict[str, Any]]


# =============================================================================
# Team Health Check Schemas
# =============================================================================


class TeamHealthCheckBase(BaseModel):
    """Base schema for team health checks."""

    satisfaction: Optional[float] = Field(None, ge=1, le=5)
    workload_balance: Optional[float] = Field(None, ge=1, le=5)
    technical_debt_pressure: Optional[float] = Field(None, ge=1, le=5)
    collaboration_quality: Optional[float] = Field(None, ge=1, le=5)
    happiness_index: Optional[float] = Field(None, ge=1, le=5)
    burnout_risk_score: Optional[float] = Field(None, ge=0, le=1)
    burnout_risk_factors: Optional[str] = Field(None, max_length=500)
    check_date: date
    respondent_count: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = Field(None, max_length=1000)


class TeamHealthCheckCreate(TeamHealthCheckBase):
    """Schema for creating team health check."""

    project_id: int
    sprint_id: Optional[int] = None


class TeamHealthCheckUpdate(BaseModel):
    """Schema for updating team health check."""

    satisfaction: Optional[float] = Field(None, ge=1, le=5)
    workload_balance: Optional[float] = Field(None, ge=1, le=5)
    technical_debt_pressure: Optional[float] = Field(None, ge=1, le=5)
    collaboration_quality: Optional[float] = Field(None, ge=1, le=5)
    happiness_index: Optional[float] = Field(None, ge=1, le=5)
    burnout_risk_score: Optional[float] = Field(None, ge=0, le=1)
    burnout_risk_factors: Optional[str] = Field(None, max_length=500)
    respondent_count: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = Field(None, max_length=1000)


class TeamHealthCheckInDB(TeamHealthCheckBase):
    """Schema for team health check from database."""

    id: int
    project_id: int
    sprint_id: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TeamHealthCheck(TeamHealthCheckInDB):
    """Full team health check response schema."""

    pass


class HealthTrend(BaseModel):
    """Health metrics trend over time."""

    check_date: date
    happiness_index: Optional[float]
    burnout_risk_score: Optional[float]


class TeamHealthSummary(BaseModel):
    """Summary of team health metrics."""

    latest_happiness_index: Optional[float]
    latest_burnout_risk: Optional[float]
    trend_direction: str  # "improving", "declining", "stable"
    checks_count: int
    trend_data: List[HealthTrend]


# =============================================================================
# CFD Snapshot Schemas
# =============================================================================


class CFDSnapshotBase(BaseModel):
    """Base schema for CFD snapshots."""

    snapshot_date: date
    backlog_count: int = 0
    todo_count: int = 0
    in_progress_count: int = 0
    in_review_count: int = 0
    testing_count: int = 0
    done_count: int = 0
    total_count: int = 0
    wip_count: int = 0
    throughput: Optional[int] = None
    avg_cycle_time_hours: Optional[float] = None


class CFDSnapshotCreate(CFDSnapshotBase):
    """Schema for creating CFD snapshot."""

    project_id: int
    sprint_id: Optional[int] = None


class CFDSnapshotInDB(CFDSnapshotBase):
    """Schema for CFD snapshot from database."""

    id: int
    project_id: int
    sprint_id: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CFDSnapshot(CFDSnapshotInDB):
    """Full CFD snapshot response schema."""

    pass


class CFDData(BaseModel):
    """CFD data for visualization."""

    snapshots: List[CFDSnapshot]
    date_range: Dict[str, date]
    status_labels: List[str]


class FlowMetrics(BaseModel):
    """Flow metrics derived from CFD data."""

    avg_lead_time_days: Optional[float]
    avg_cycle_time_hours: Optional[float]
    avg_throughput_per_day: Optional[float]
    wip_trend: str  # "increasing", "decreasing", "stable"
    bottleneck_status: Optional[str]  # Status with highest accumulation
