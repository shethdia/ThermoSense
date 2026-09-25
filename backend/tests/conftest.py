import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.database import Base, get_db
from app.main import app
from app.ml import Predictor
from app.models import User


@pytest.fixture(scope="session")
def predictor(tmp_path_factory):
    artifact = tmp_path_factory.mktemp("model") / "random_forest.joblib"
    return Predictor(artifact)


@pytest.fixture
def test_context(predictor):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with TestingSession() as db:
        db.add(User(id=1, name="Test Admin", email="admin@test.local", hashed_password=hash_password("test-password"), role="admin"))
        db.add(User(id=2, name="Test User", email="user@test.local", hashed_password=hash_password("test-password"), role="user"))
        db.add(User(id=3, name="Emergency Team", email="team@test.local", hashed_password=hash_password("test-password"), role="emergency_team"))
        db.commit()

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    import app.main as main_module
    main_module.predictor = predictor
    client = TestClient(app)
    yield client, TestingSession
    client.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def login_headers(test_context):
    client, _ = test_context
    response = client.post("/api/auth/login", json={"email": "admin@test.local", "password": "test-password"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
