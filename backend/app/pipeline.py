from sqlalchemy.orm import Session

from app.blockchain import append_lock, append_prediction
from app.fog import process_reading
from app.ml import Predictor
from app.models import Alert, Device, Prediction, SensorReading, User
from app.schemas import SensorInput


def ingest(db: Session, payload: SensorInput, predictor: Predictor) -> SensorReading:
    # One local API process serializes appends through the enclosing commit so
    # concurrent ingestion calls cannot claim the same chain index.
    with append_lock:
        return _ingest_locked(db, payload, predictor)


def _ingest_locked(db: Session, payload: SensorInput, predictor: Predictor) -> SensorReading:
    fog = process_reading(payload)
    risk, confidence = predictor.predict(fog.features)
    user = db.get(User, payload.user_id)
    if user is None:
        user = User(id=payload.user_id, name=f"Worker {payload.user_id}",
                    email=f"worker-{payload.user_id}@local.invalid", role="user", is_account=False)
        db.add(user)
    device = db.get(Device, payload.device_id)
    if device is None:
        device = Device(id=payload.device_id, device_code=f"SIM-{payload.device_id:03d}")
        db.add(device)
    record = SensorReading(user_id=payload.user_id, device_id=payload.device_id,
        timestamp=payload.timestamp, body_temperature=fog.raw_features[0], heart_rate=fog.raw_features[1],
        ambient_temperature=fog.raw_features[2], humidity=fog.raw_features[3], risk=risk, confidence=confidence)
    db.add(record)
    db.flush()
    prediction = Prediction(reading_id=record.id, risk=risk, confidence=confidence)
    db.add(prediction)
    db.flush()
    append_prediction(db, prediction, record)
    if risk in {"MODERATE", "HIGH"}:
        level = "Warning" if risk == "MODERATE" else "Emergency"
        db.add(Alert(user_id=payload.user_id, prediction_id=prediction.id, risk=risk,
            message=f"{level}: {risk.lower()} heat-stress risk detected for Worker {payload.user_id}.",
            sensor_values={"body_temperature": record.body_temperature, "heart_rate": record.heart_rate,
                "ambient_temperature": record.ambient_temperature, "humidity": record.humidity}))
    db.commit()
    db.refresh(record)
    return record

