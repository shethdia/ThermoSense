from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SensorInput(BaseModel):
    user_id: int = Field(gt=0)
    device_id: int = Field(gt=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    body_temperature: float = Field(ge=30, le=45)
    heart_rate: float = Field(ge=30, le=240)
    ambient_temperature: float = Field(ge=-20, le=65)
    humidity: float = Field(ge=0, le=100)


class ReadingResult(SensorInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    risk: Literal["LOW", "MODERATE", "HIGH"]
    confidence: float
    processed_at: datetime


class AlertResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    prediction_id: int
    timestamp: datetime
    risk: Literal["MODERATE", "HIGH"]
    message: str
    sensor_values: dict[str, float]
    status: Literal["ACTIVE", "RESOLVED"]


class SimulationConfig(BaseModel):
    scenario: Literal["normal", "moderate", "high"] = "normal"
    users: int = Field(default=3, ge=1, le=50)
    interval_seconds: float = Field(default=2, ge=0.5, le=60)


class LoginInput(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class UserResult(BaseModel):
    id: int
    name: str
    email: str
    role: Literal["admin", "user", "emergency_team"]


class CreateUserInput(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["user", "emergency_team"] = "user"


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserResult

