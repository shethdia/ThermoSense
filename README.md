# ThermoSense

ThermoSense is a software-only heat stress monitoring research prototype. Its P0 flow is **simulated sensor → validated ingestion → local fog boundary → trained Random Forest → risk → PostgreSQL**. It is a BTech engineering/research prototype, not a clinically validated medical device; predictions are not medical diagnoses.

## Current implementation

The backend exposes sensor ingestion, polling, fog status, simulator control, alert listing/resolution, user details, overview statistics, historical reading filters, risk analytics, model evaluation, and blockchain verification. Moderate and High predictions persist in-app warning/emergency alerts. Each prediction and source reading is also appended as a SHA-256 chained block in the same PostgreSQL transaction. The simulator creates smoothly changing readings for Normal, Moderate, or High scenarios and sends them through the same ingestion function as direct API readings. The ML artifact is trained from a reproducible synthetic demonstration dataset on first startup and saved at `backend/data/random_forest.joblib`; its evaluation metrics are saved beside it.

## Run locally

1. Install Docker Desktop, Python 3.11+, and copy `backend/.env.example` to `backend/.env` for local configuration. Set a unique JWT secret and admin password before sharing or deploying the app.
2. Start PostgreSQL from the repository root: `docker compose up -d postgres`.
3. In `backend`, install dependencies: `python -m pip install -r requirements.txt`.
4. Start the API from `backend`: `uvicorn app.main:app --reload`.
5. Open [http://localhost:8000/docs](http://localhost:8000/docs). The API creates tables and trains/loads its model at startup.
6. In another terminal, enter `frontend`, run `npm install`, then `npm run dev`. Open the Vite URL (normally [http://localhost:5173](http://localhost:5173)).

For a production frontend bundle, run `npm run build` from `frontend`; use `npm run preview` to serve the compiled app locally.

The default database URL and local demonstration credentials are in `.env.example` (these are development-only values). Use `DATABASE_URL` to point to another PostgreSQL instance. `MODEL_PATH` may be absolute or relative to the backend directory.

Copy `backend/.env.example` to `backend/.env` and replace `JWT_SECRET` and `ADMIN_PASSWORD` before any shared or deployed use. The local demonstration admin signs in with the configured `ADMIN_EMAIL` and `ADMIN_PASSWORD` (defaults: `admin@thermosense.local` / `ChangeMe-1234`). The admin can create User and Emergency Team accounts through `POST /api/users`. A small additive startup migration upgrades the prototype's earlier `users` table with authentication fields.

## API quick start

- `POST /api/simulation/start` with `{"scenario":"high","users":3,"interval_seconds":2}`
- `GET /api/readings?limit=30`
- `GET /api/fog/stats`
- `GET /api/simulation/status`
- `POST /api/simulation/stop`
- `POST /api/readings` to submit a reading through the modular ingestion boundary
- `GET /api/dashboard/overview`, `/api/monitoring/users`, and `/api/fog/stats`
- `GET /api/alerts`, `PATCH /api/alerts/{id}/resolve`
- `GET /api/readings?user_id=1&risk=HIGH&limit=100`
- `GET /api/analytics/summary`, `/api/analytics/model`
- `GET /api/blockchain/records`, `/api/blockchain/verify`
- `POST /api/auth/login`, `GET /api/auth/me`
- Admin-only user management: `GET /api/users`, `POST /api/users`

For protected requests, first send `POST /api/auth/login` with JSON `{"email":"admin@thermosense.local","password":"ChangeMe-1234"}`. Then add the returned token as `Authorization: Bearer <access_token>`. Swagger UI supports the same bearer token through its Authorize control.

Risk labels come from the trained classifier and are `LOW`, `MODERATE`, or `HIGH`. Request values are validated with physical plausibility bounds before processing. The fog stage validates again, applies a three-reading rolling median per device to suppress isolated spikes, then scales values to the sensor schema's 0–1 ranges for the Random Forest. Missing required fields are rejected at ingestion rather than replaced with fabricated values. Original sensor measurements are retained in history and blockchain records; only filtered and normalized values feed the classifier.

## Architecture and next priorities

`backend/app/schemas.py` defines the source-neutral reading contract. `pipeline.py` is shared by the simulator and API ingestion. `fog.py` and `ml.py` hold local processing and model behavior, independent of transport. A future sensor adapter should validate device messages into `SensorInput` and call the existing ingestion pipeline; fog, ML, persistence, alert, and dashboard modules can then stay unchanged. This version has no MQTT, ESP32, or physical sensor dependencies.

P0 through P3 and the P4 polish pass are implemented. The React app polls the API while the simulation runs and includes a JWT login screen, admin account management, date-range history filters, role-aware alert actions, responsive layouts, and explicit loading/error/empty states. Admin accounts control the simulator and manage accounts; Emergency Team members can resolve alerts; authenticated roles can read monitoring data. The current model uses a synthetic demonstration dataset and is not clinically validated.

## Roles and tests

Roles are `admin`, `user`, and `emergency_team`. Admin controls simulation and account creation; Admin and Emergency Team can resolve alerts; all signed-in roles can view monitoring records, analytics, and blockchain verification. The frontend stores the short-lived JWT in browser local storage and attaches it to API requests.

Run backend tests from `backend`: `python -m pip install -r requirements.txt`, then `pytest`. The suite uses an isolated in-memory SQLite database and checks data validation, fog preprocessing, all risk classes, persistence, alerts, blockchain tamper detection, login, authorization, and API validation. PostgreSQL remains the runtime database configured for the app.
