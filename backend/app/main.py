import asyncio
import random
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.blockchain import verify_chain
from app.auth import create_access_token, get_current_user, hash_password, require_roles, verify_password
from app.database import Base, SessionLocal, engine, get_db, reserve_account_ids, upgrade_user_auth_schema
from app.fog import fog_processor
from app.ml import Predictor
from app.models import Alert, BlockchainRecord, Device, Prediction, SensorReading, User
from app.pipeline import ingest
from app.schemas import AlertResult, CreateUserInput, LoginInput, ReadingResult, SensorInput, SimulationConfig, TokenResponse, UserResult

predictor: Predictor
simulation = {"running": False, "scenario": "normal", "users": 3, "interval_seconds": 2.0}
sim_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global predictor
    Base.metadata.create_all(bind=engine)
    upgrade_user_auth_schema()
    with SessionLocal() as db:
        admin = db.query(User).filter(User.email == settings.admin_email.lower()).first()
        if admin is None:
            db.add(User(id=1_000_000, name="ThermoSense Admin", email=settings.admin_email.lower(),
                hashed_password=hash_password(settings.admin_password), role="admin", is_account=True))
            db.commit()
    reserve_account_ids()
    model_path = Path(settings.model_path)
    if not model_path.is_absolute():
        model_path = Path(__file__).resolve().parents[1] / model_path
    predictor = Predictor(model_path)
    yield
    if sim_task:
        sim_task.cancel()


app = FastAPI(title="ThermoSense API", version="0.1.0", description="Heat stress monitoring research prototype. Not for clinical diagnosis.", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.cors_origins.split(",")], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"status": "online", "database": "configured", "model": "Random Forest"}


def user_result(user: User) -> UserResult:
    return UserResult(id=user.id, name=user.name, email=user.email or "", role=user.role)


@app.post("/api/auth/login", response_model=TokenResponse)
def login(payload: LoginInput, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.strip().lower()).first()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"})
    token = create_access_token(user)
    return {"access_token": token, "expires_in": settings.jwt_expire_minutes * 60, "user": user_result(user)}


@app.get("/api/auth/me", response_model=UserResult)
def auth_me(user: User = Depends(get_current_user)):
    return user_result(user)


@app.get("/api/users", response_model=list[UserResult])
def list_users(user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    return [user_result(item) for item in db.scalars(select(User).where(User.is_account.is_(True)).order_by(User.id))]


@app.post("/api/users", response_model=UserResult, status_code=201)
def create_user(payload: CreateUserInput, user: User = Depends(require_roles("admin")),
                db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    account = User(name=payload.name.strip(), email=email, hashed_password=hash_password(payload.password), role=payload.role, is_account=True)
    db.add(account)
    db.commit()
    db.refresh(account)
    return user_result(account)


@app.post("/api/readings", response_model=ReadingResult)
def submit_reading(payload: SensorInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return ingest(db, payload, predictor)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/readings", response_model=list[ReadingResult])
def get_readings(limit: int = 100, user_id: int | None = None, risk: str | None = None,
                 start: datetime | None = None, end: datetime | None = None,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(SensorReading)
    if user_id is not None:
        query = query.where(SensorReading.user_id == user_id)
    if risk:
        query = query.where(SensorReading.risk == risk.upper())
    if start:
        query = query.where(SensorReading.timestamp >= start)
    if end:
        query = query.where(SensorReading.timestamp <= end)
    return list(db.scalars(query.order_by(SensorReading.timestamp.desc()).limit(min(max(limit, 1), 500))))


@app.get("/api/monitoring/users", response_model=list[ReadingResult])
def latest_by_user(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(SensorReading).order_by(SensorReading.timestamp.desc())).all()
    latest = {}
    for row in rows:
        latest.setdefault(row.user_id, row)
    return list(latest.values())


@app.get("/api/users/{user_id}")
def user_details(user_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    readings = list(db.scalars(select(SensorReading).where(SensorReading.user_id == user_id)
        .order_by(SensorReading.timestamp.desc()).limit(100)))
    alerts = list(db.scalars(select(Alert).where(Alert.user_id == user_id)
        .order_by(Alert.timestamp.desc()).limit(50)))
    return {"id": user.id, "name": user.name, "device_ids": sorted({r.device_id for r in readings}),
            "readings": readings, "alerts": alerts}


@app.get("/api/alerts", response_model=list[AlertResult])
def list_alerts(status: str | None = None, risk: str | None = None, limit: int = 200,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(Alert)
    if status and status.lower() != "all":
        query = query.where(Alert.status == status.upper())
    if risk and risk.lower() != "all":
        query = query.where(Alert.risk == risk.upper())
    return list(db.scalars(query.order_by(Alert.timestamp.desc()).limit(min(max(limit, 1), 500))))


@app.patch("/api/alerts/{alert_id}/resolve", response_model=AlertResult)
def resolve_alert(alert_id: int, user: User = Depends(require_roles("admin", "emergency_team")), db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(404, "Alert not found")
    alert.status = "RESOLVED"
    db.commit()
    db.refresh(alert)
    return alert


@app.get("/api/dashboard/overview")
def dashboard_overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(SensorReading).order_by(SensorReading.timestamp.desc())).all()
    latest = {}
    for row in rows:
        latest.setdefault(row.user_id, row)
    active_alerts = db.scalar(select(func.count(Alert.id)).where(Alert.status == "ACTIVE")) or 0
    monitored_devices = db.scalar(select(func.count(Device.id))) or 0
    high_risk = sum(row.risk == "HIGH" for row in latest.values())
    return {"monitored_users": len(latest), "active_devices": monitored_devices,
        "high_risk_users": high_risk, "active_alerts": active_alerts,
        "latest_readings": list(latest.values()), "simulation": simulation}


@app.get("/api/analytics/summary")
def analytics_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(SensorReading).order_by(SensorReading.timestamp.desc()).limit(240)))
    total = db.scalar(select(func.count(Prediction.id))) or 0
    risk_counts = {risk: db.scalar(select(func.count(Prediction.id)).where(Prediction.risk == risk)) or 0
                   for risk in ("LOW", "MODERATE", "HIGH")}
    averages = {}
    for key in ("body_temperature", "heart_rate", "ambient_temperature", "humidity"):
        averages[key] = round(db.scalar(select(func.avg(getattr(SensorReading, key)))) or 0, 2)
    trend = [{"timestamp": row.timestamp, "user_id": row.user_id, "body_temperature": row.body_temperature,
        "heart_rate": row.heart_rate, "ambient_temperature": row.ambient_temperature,
        "humidity": row.humidity, "risk": row.risk} for row in reversed(rows)]
    return {"total_predictions": total, "risk_distribution": risk_counts, "averages": averages,
        "trend": trend, "model_metrics": predictor.metrics}


@app.get("/api/analytics/model")
def model_metrics(user: User = Depends(get_current_user)):
    return predictor.metrics


@app.get("/api/blockchain/verify")
def blockchain_verification(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return verify_chain(db)


@app.get("/api/blockchain/records")
def blockchain_records(limit: int = 100, offset: int = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    safe_limit = min(max(limit, 1), 500)
    blocks = list(db.scalars(select(BlockchainRecord).order_by(BlockchainRecord.block_index.desc())
        .offset(max(offset, 0)).limit(safe_limit)))
    total = db.scalar(select(func.count(BlockchainRecord.id))) or 0
    return {"total": total, "items": blocks}


@app.get("/api/fog/stats")
def fog_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    total = db.scalar(select(func.count(SensorReading.id))) or 0
    latest = db.scalar(select(func.max(SensorReading.processed_at)))
    stats = fog_processor.stats()
    return {"online": True, "processed_readings": total, **stats,
            "latest_processed_at": latest or stats["latest_processed_at"],
            "note": "Per-device rolling median filtering and bounded feature normalization run locally."}


async def run_simulation():
    values = {}
    while simulation["running"]:
        scenario = simulation["scenario"]
        for user_id in range(1, simulation["users"] + 1):
            current = values.setdefault(user_id, [36.7, 74.0, 24.0, 50.0])
            target = {"normal": [36.7, 74, 24, 50], "moderate": [37.7, 88, 34, 62], "high": [39.0, 132, 41, 72]}[scenario]
            for i in range(4):
                current[i] += (target[i] - current[i]) * .16 + random.uniform(-[.12, 2.2, .5, 1.5][i], [.12, 2.2, .5, 1.5][i])
            payload = SensorInput(user_id=user_id, device_id=user_id, timestamp=datetime.now(timezone.utc),
                body_temperature=round(current[0], 2), heart_rate=round(current[1], 1),
                ambient_temperature=round(current[2], 1), humidity=round(current[3], 1))
            with SessionLocal() as db:
                ingest(db, payload, predictor)
        await asyncio.sleep(simulation["interval_seconds"])


@app.post("/api/simulation/start")
async def start_simulation(config: SimulationConfig, user: User = Depends(require_roles("admin"))):
    global sim_task
    if sim_task and not sim_task.done():
        sim_task.cancel()
    simulation.update(running=True, **config.model_dump())
    sim_task = asyncio.create_task(run_simulation())
    return simulation


@app.post("/api/simulation/stop")
async def stop_simulation(user: User = Depends(require_roles("admin"))):
    simulation["running"] = False
    return simulation


@app.get("/api/simulation/status")
def simulation_status(user: User = Depends(get_current_user)):
    return simulation

