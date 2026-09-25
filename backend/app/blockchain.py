import hashlib
import json
import threading
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BlockchainRecord, Prediction, SensorReading

append_lock = threading.Lock()
GENESIS_HASH = "0" * 64


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _utc_iso(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _reading_payload(reading: SensorReading) -> dict:
    return {"user_id": reading.user_id, "device_id": reading.device_id,
        "timestamp": _utc_iso(reading.timestamp),
        "body_temperature": reading.body_temperature, "heart_rate": reading.heart_rate,
        "ambient_temperature": reading.ambient_temperature, "humidity": reading.humidity}


def _block_hash(index: int, timestamp: str, record_id: int, risk: str,
                data_hash: str, previous_hash: str) -> str:
    body = {"block_index": index, "timestamp": timestamp, "record_id": record_id,
        "risk": risk, "data_hash": data_hash, "previous_hash": previous_hash}
    return hashlib.sha256(_canonical(body)).hexdigest()


def append_prediction(db: Session, prediction: Prediction, reading: SensorReading) -> BlockchainRecord:
    """Append a prediction and its source reading to the local SHA-256 chain."""
    previous = db.scalar(select(BlockchainRecord).order_by(BlockchainRecord.block_index.desc()).limit(1))
    index = previous.block_index + 1 if previous else 0
    previous_hash = previous.current_hash if previous else GENESIS_HASH
    timestamp = prediction.predicted_at
    timestamp_iso = _utc_iso(timestamp)
    data_hash = hashlib.sha256(_canonical(_reading_payload(reading))).hexdigest()
    current_hash = _block_hash(index, timestamp_iso, prediction.id, prediction.risk, data_hash, previous_hash)
    block = BlockchainRecord(block_index=index, timestamp=timestamp, prediction_id=prediction.id,
        risk=prediction.risk, data_hash=data_hash, previous_hash=previous_hash, current_hash=current_hash)
    db.add(block)
    db.flush()
    return block


def verify_chain(db: Session) -> dict:
    rows = db.execute(select(BlockchainRecord, Prediction, SensorReading)
        .join(Prediction, BlockchainRecord.prediction_id == Prediction.id)
        .join(SensorReading, Prediction.reading_id == SensorReading.id)
        .order_by(BlockchainRecord.block_index.asc())).all()
    expected_previous = GENESIS_HASH
    for expected_index, (block, prediction, reading) in enumerate(rows):
        timestamp_iso = _utc_iso(block.timestamp)
        data_hash = hashlib.sha256(_canonical(_reading_payload(reading))).hexdigest()
        calculated_hash = _block_hash(block.block_index, timestamp_iso, prediction.id,
            prediction.risk, block.data_hash, block.previous_hash)
        if block.block_index != expected_index:
            return {"valid": False, "blocks_verified": expected_index,
                    "broken_at": block.block_index, "reason": "block index gap"}
        if block.previous_hash != expected_previous:
            return {"valid": False, "blocks_verified": expected_index,
                    "broken_at": block.block_index, "reason": "previous hash mismatch"}
        if block.risk != prediction.risk or block.data_hash != data_hash:
            return {"valid": False, "blocks_verified": expected_index,
                    "broken_at": block.block_index, "reason": "record data mismatch"}
        if block.current_hash != calculated_hash:
            return {"valid": False, "blocks_verified": expected_index,
                    "broken_at": block.block_index, "reason": "block hash mismatch"}
        expected_previous = block.current_hash
    return {"valid": True, "blocks_verified": len(rows), "broken_at": None, "reason": None,
            "latest_hash": expected_previous if rows else None}

