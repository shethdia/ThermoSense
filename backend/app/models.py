from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="user", server_default="user")
    is_account: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    readings: Mapped[list["SensorReading"]] = relationship(back_populates="user")


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_code: Mapped[str] = mapped_column(String(80), unique=True)
    readings: Mapped[list["SensorReading"]] = relationship(back_populates="device")


class SensorReading(Base):
    __tablename__ = "sensor_readings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    body_temperature: Mapped[float] = mapped_column(Float)
    heart_rate: Mapped[float] = mapped_column(Float)
    ambient_temperature: Mapped[float] = mapped_column(Float)
    humidity: Mapped[float] = mapped_column(Float)
    risk: Mapped[str] = mapped_column(String(12), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user: Mapped[User] = relationship(back_populates="readings")
    device: Mapped[Device] = relationship(back_populates="readings")


class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reading_id: Mapped[int] = mapped_column(ForeignKey("sensor_readings.id"), unique=True, index=True)
    risk: Mapped[str] = mapped_column(String(12), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    model_version: Mapped[str] = mapped_column(String(40), default="rf-synthetic-v1")
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    risk: Mapped[str] = mapped_column(String(12), index=True)
    message: Mapped[str] = mapped_column(String(240))
    sensor_values: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)


class BlockchainRecord(Base):
    __tablename__ = "blockchain_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    block_index: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"), unique=True, index=True)
    risk: Mapped[str] = mapped_column(String(12), index=True)
    data_hash: Mapped[str] = mapped_column(String(64))
    previous_hash: Mapped[str] = mapped_column(String(64))
    current_hash: Mapped[str] = mapped_column(String(64), unique=True)

