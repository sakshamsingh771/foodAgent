import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
Rung = Literal["R1", "R2", "R3", "R4"]


def _email(v: str) -> str:
    v = v.strip().lower()
    if not EMAIL_RE.match(v) or len(v) > 254:
        raise ValueError("Enter a valid email address.")
    return v


class RegisterIn(BaseModel):
    organization_name: str = Field(min_length=2, max_length=160)
    full_name: str = Field(min_length=2, max_length=120)
    email: str
    password: str = Field(min_length=10, max_length=128)
    _e = field_validator("email")(_email)


class LoginIn(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=128)
    _e = field_validator("email")(_email)


class RefreshIn(BaseModel):
    refresh_token: str


class UserCreateIn(BaseModel):
    email: str
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=10, max_length=128)
    role: Literal["ADMIN", "OPERATIONS_MANAGER", "RECOVERY_MANAGER", "LOGISTICS", "AUDITOR"]
    _e = field_validator("email")(_email)


class LotIn(BaseModel):
    plant_id: uuid.UUID
    product_id: uuid.UUID
    lot_code: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9\-_.]+$")
    quantity_kg: float = Field(gt=0, le=100000)
    produced_at: datetime
    safe_until: datetime
    storage: Literal["ambient", "chilled", "frozen"] = "chilled"


class CaseCreateIn(BaseModel):
    lot_id: uuid.UUID


class ApproveIn(BaseModel):
    rung: Rung
    recipient_id: uuid.UUID | None = None
    note: str = Field(default="", max_length=500)


class NoteIn(BaseModel):
    note: str = Field(default="", max_length=500)


class ReplanIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)
    exclude_rung: Rung | None = None


class RecipientResponseIn(BaseModel):
    accept: bool
    reason: str | None = Field(default=None, max_length=300)


class SimulateIn(BaseModel):
    pickup_delay_min: int = Field(ge=0, le=720)
    acceptance_prob: float = Field(ge=0, le=1)
    handover_buffer_min: int = Field(ge=0, le=240)
    remaining_minutes: int = Field(ge=0, le=7 * 24 * 60)


class PickupIn(BaseModel):
    scheduled_for: datetime
    logistics_user_id: uuid.UUID | None = None


class PickupStatusIn(BaseModel):
    status: Literal["assigned", "scheduled", "in_transit", "arrived", "cancelled"]


class DelayIn(BaseModel):
    minutes: int = Field(ge=5, le=480)
    reason: str = Field(min_length=3, max_length=200)


class HandoverIn(BaseModel):
    received_kg: float | None = Field(default=None, gt=0)


class ScenarioIn(BaseModel):
    kind: str
    target_id: str


class ScenarioApplyIn(ScenarioIn):
    confirm: bool = False


Strategy = Literal["max_recovery", "fastest", "lowest_distance", "lowest_risk", "non_human_pathway"]


class AllocPlanIn(BaseModel):
    strategy: Strategy = "max_recovery"
    allow_split: bool = True


class AllocCommitIn(AllocPlanIn):
    confirm: bool = False  # committing reserves quantity, so it must be explicit
    note: str = Field(default="", max_length=500)


class AllocSimIn(BaseModel):
    scenario: Literal["none", "recipient_rejection", "capacity_reduction", "vehicle_delay", "missing_evidence", "no_feasible_option"] = "none"
    recipient_id: str | None = None
    capacity_kg: float | None = Field(default=None, ge=0, le=1_000_000)
    delay_minutes: int = Field(default=0, ge=0, le=720)
    strategy: Strategy = "max_recovery"


class AllocRespondIn(BaseModel):
    accept: bool
    reason: str | None = Field(default=None, max_length=300)
    accepted_kg: float | None = Field(default=None, gt=0, le=1_000_000)


class AllocReasonIn(BaseModel):
    reason: str = Field(default="", max_length=300)


class TransportEventIn(BaseModel):
    kind: Literal["delay", "failure"]
    minutes: int = Field(default=0, ge=0, le=720)
    reason: str = Field(min_length=3, max_length=200)


class UserUpdateIn(BaseModel):
    role: Literal["ADMIN", "OPERATIONS_MANAGER", "RECOVERY_MANAGER", "LOGISTICS", "AUDITOR"] | None = None
    is_active: bool | None = None
    reason: str | None = Field(None, max_length=200)


class LotAdjustIn(BaseModel):
    delta_kg: float = Field(allow_inf_nan=False)
    reason: str = Field(min_length=5, max_length=200)
