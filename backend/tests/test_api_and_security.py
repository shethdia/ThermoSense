def test_protected_api_requires_a_token(test_context):
    client, _ = test_context
    response = client.get("/api/dashboard/overview")
    assert response.status_code == 401


def test_login_returns_identity_and_bearer_token(test_context):
    client, _ = test_context
    response = client.post("/api/auth/login", json={"email": "admin@test.local", "password": "test-password"})
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "admin"
    token = response.json()["access_token"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["email"] == "admin@test.local"


def test_regular_user_cannot_control_simulator(test_context):
    client, _ = test_context
    token = client.post("/api/auth/login", json={"email": "user@test.local", "password": "test-password"}).json()["access_token"]
    response = client.post("/api/simulation/start", json={"scenario": "normal"}, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_admin_can_create_an_emergency_team_account(test_context, login_headers):
    client, _ = test_context
    response = client.post("/api/users", headers=login_headers, json={"name": "Response Team", "email": "response@test.local",
        "password": "a-long-test-password", "role": "emergency_team"})
    assert response.status_code == 201
    assert response.json()["role"] == "emergency_team"
    assert any(item["email"] == "response@test.local" for item in client.get("/api/users", headers=login_headers).json())


def test_regular_user_cannot_list_accounts(test_context):
    client, _ = test_context
    token = client.post("/api/auth/login", json={"email": "user@test.local", "password": "test-password"}).json()["access_token"]
    response = client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_emergency_team_can_resolve_but_regular_user_cannot(test_context, login_headers):
    client, _ = test_context
    reading = client.post("/api/readings", headers=login_headers, json={"user_id": 24, "device_id": 24,
        "body_temperature": 39, "heart_rate": 132, "ambient_temperature": 41, "humidity": 72})
    assert reading.status_code == 200
    alert = client.get("/api/alerts", headers=login_headers).json()[0]
    user_token = client.post("/api/auth/login", json={"email": "user@test.local", "password": "test-password"}).json()["access_token"]
    team_token = client.post("/api/auth/login", json={"email": "team@test.local", "password": "test-password"}).json()["access_token"]
    denied = client.patch(f"/api/alerts/{alert['id']}/resolve", headers={"Authorization": f"Bearer {user_token}"})
    allowed = client.patch(f"/api/alerts/{alert['id']}/resolve", headers={"Authorization": f"Bearer {team_token}"})
    assert denied.status_code == 403
    assert allowed.status_code == 200 and allowed.json()["status"] == "RESOLVED"


def test_reading_endpoint_validates_payload(test_context, login_headers):
    client, _ = test_context
    response = client.post("/api/readings", json={"user_id": 4, "device_id": 4, "body_temperature": 60,
        "heart_rate": 80, "ambient_temperature": 25, "humidity": 50}, headers=login_headers)
    assert response.status_code == 422

