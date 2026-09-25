import pytest
from pydantic import ValidationError

from app.fog import FogProcessor, normalize_features, process_reading
from app.schemas import SensorInput


def test_sensor_schema_rejects_out_of_range_values():
    with pytest.raises(ValidationError):
        SensorInput(user_id=1, device_id=1, body_temperature=52, heart_rate=80,
            ambient_temperature=25, humidity=50)


def test_fog_processing_filters_and_normalizes_features():
    reading = SensorInput(user_id=1, device_id=1, body_temperature=37.2, heart_rate=88,
        ambient_temperature=30, humidity=55)
    result = process_reading(reading, FogProcessor())
    assert result.raw_features == [37.2, 88.0, 30.0, 55.0]
    assert result.filtered_features == result.raw_features
    assert result.features == normalize_features(result.raw_features)
    assert all(0 <= value <= 1 for value in result.features)
    assert result.latency_ms >= 0


def test_fog_median_suppresses_single_reading_spike():
    processor = FogProcessor()
    readings = [
        SensorInput(user_id=1, device_id=9, body_temperature=value, heart_rate=80,
            ambient_temperature=25, humidity=50)
        for value in [37.0, 43.0, 37.1]
    ]
    results = [process_reading(reading, processor) for reading in readings]
    assert results[-1].filtered_features[0] == 37.1


def test_random_forest_returns_supported_classes(predictor):
    samples = [[36.7, 74, 24, 50], [37.7, 88, 34, 62], [39, 132, 41, 72]]
    predictions = [predictor.predict(normalize_features(sample)) for sample in samples]
    assert [risk for risk, _ in predictions] == ["LOW", "MODERATE", "HIGH"]
    assert all(0 <= confidence <= 1 for _, confidence in predictions)

