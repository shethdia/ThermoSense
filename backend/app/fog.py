from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from statistics import median
from threading import Lock
from time import perf_counter

from app.schemas import SensorInput

BOUNDS = ((30.0, 45.0), (30.0, 240.0), (-20.0, 65.0), (0.0, 100.0))


def normalize_features(values: list[float]) -> list[float]:
    """Scale validated raw sensor features to the schema's [0, 1] ranges."""
    if len(values) != len(BOUNDS):
        raise ValueError("Exactly four sensor features are required")
    if not all(isfinite(value) for value in values):
        raise ValueError("Sensor values must be finite")
    for value, (low, high) in zip(values, BOUNDS):
        if not low <= value <= high:
            raise ValueError("Sensor value is outside its supported range")
    return [(value - low) / (high - low) for value, (low, high) in zip(values, BOUNDS)]


@dataclass
class FogResult:
    features: list[float]
    raw_features: list[float]
    filtered_features: list[float]
    latency_ms: float


class FogProcessor:
    """Small per-device median window with bounded state and process statistics."""
    def __init__(self):
        self._windows: OrderedDict[int, deque[list[float]]] = OrderedDict()
        self._lock = Lock()
        self._received = 0
        self._processed = 0
        self._invalid = 0
        self._latency_total = 0.0
        self._latest = None

    def process(self, reading: SensorInput) -> FogResult:
        started = perf_counter()
        raw = [reading.body_temperature, reading.heart_rate,
               reading.ambient_temperature, reading.humidity]
        with self._lock:
            self._received += 1
            try:
                normalize_features(raw)  # Finite and range check at the fog boundary too.
                window = self._windows.setdefault(reading.device_id, deque(maxlen=3))
                window.append(raw)
                self._windows.move_to_end(reading.device_id)
                if len(self._windows) > 500:
                    self._windows.popitem(last=False)
                filtered = [float(median(column)) for column in zip(*window)]
                features = normalize_features(filtered)
                latency = (perf_counter() - started) * 1000
                self._processed += 1
                self._latency_total += latency
                self._latest = datetime.now(timezone.utc).isoformat()
                return FogResult(features, raw, filtered, latency)
            except Exception:
                self._invalid += 1
                raise

    def stats(self) -> dict:
        with self._lock:
            return {"received_readings": self._received,
                    "successfully_processed": self._processed,
                    "invalid_readings": self._invalid,
                    "average_processing_ms": round(self._latency_total / self._processed, 4) if self._processed else 0.0,
                    "latest_processed_at": self._latest}


fog_processor = FogProcessor()


def process_reading(reading: SensorInput, processor: FogProcessor | None = None) -> FogResult:
    return (processor or fog_processor).process(reading)
