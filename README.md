# ThermoSense

ThermoSense is a student project that simulates heat-stress readings and displays risk levels in a web dashboard. It is for demonstration only and is not a medical device.

## What you need

- Python 3.11 or later
- Node.js
- PostgreSQL

## Setup

Create a PostgreSQL database named `thermosense` and a user named `thermosense` with password `thermosense`. In pgAdmin's Query Tool, connected as a database administrator, you can run:

```sql
CREATE USER thermosense WITH PASSWORD 'thermosense';
CREATE DATABASE thermosense OWNER thermosense;
```

In PowerShell, from the project folder, copy the sample settings and install the backend packages:

```powershell
Copy-Item backend\.env.example backend\.env
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Start the API in this window:

```powershell
python -m uvicorn app.main:app --reload
```

Open a second PowerShell window and start the dashboard:

```powershell
cd "C:\path\to\ThermoSense\frontend"
npm install
npm run dev
```

Open the local address printed by Vite, usually [http://localhost:5173](http://localhost:5173). Sign in with `admin@thermosense.local` and `ChangeMe-1234`, then start the simulation from the dashboard. The API documentation is at [http://localhost:8000/docs](http://localhost:8000/docs).

If your PostgreSQL username, password, or database name is different, update `DATABASE_URL` in `backend/.env`.

## Model

The app uses a scikit-learn Random Forest classifier trained on generated sample data. The model is saved locally and loaded when the API starts. Its risk predictions are for demonstration and have not been clinically validated.

## Tests

From the `backend` folder, run `python -m pytest`.
