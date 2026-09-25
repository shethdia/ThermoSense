from sqlalchemy import select

from app.blockchain import verify_chain
from app.models import Alert, BlockchainRecord, SensorReading


def test_high_reading_persists_prediction_alert_and_block(test_context, login_headers):
    client, TestingSession = test_context
    response = client.post("/api/readings", headers=login_headers, json={"user_id": 22, "device_id": 22,
        "body_temperature": 39, "heart_rate": 132, "ambient_temperature": 41, "humidity": 72})
    assert response.status_code == 200
    assert response.json()["risk"] == "HIGH"
    with TestingSession() as db:
        reading = db.scalar(select(SensorReading).where(SensorReading.user_id == 22))
        alert = db.scalar(select(Alert).where(Alert.user_id == 22))
        block = db.scalar(select(BlockchainRecord))
        assert reading is not None and alert is not None and block is not None
        assert alert.risk == "HIGH" and alert.status == "ACTIVE"
        assert verify_chain(db)["valid"] is True


def test_blockchain_verification_detects_tampering(test_context, login_headers):
    client, TestingSession = test_context
    client.post("/api/readings", headers=login_headers, json={"user_id": 23, "device_id": 23,
        "body_temperature": 39, "heart_rate": 132, "ambient_temperature": 41, "humidity": 72})
    with TestingSession() as db:
        block = db.scalar(select(BlockchainRecord))
        block.data_hash = "f" * 64
        db.commit()
        result = verify_chain(db)
        assert result["valid"] is False
        assert result["broken_at"] == 0
