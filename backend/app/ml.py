from pathlib import Path
import json

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split
from app.fog import normalize_features

FEATURES = ["body_temperature", "heart_rate", "ambient_temperature", "humidity"]
LABELS = ["LOW", "MODERATE", "HIGH"]
MODEL_VERSION = "rf-synthetic-v2"


def train_model(path: Path) -> dict:
    rng = np.random.default_rng(42)
    n = 6000
    ambient = rng.uniform(18, 48, n)
    humidity = rng.uniform(15, 95, n)
    body = rng.normal(36.8, 1.8, n).clip(34, 43)
    heart = (rng.normal(72, 15, n) + np.maximum(ambient - 25, 0) * 1.5).clip(45, 180)
    heat_load = (body - 37.2) * 2.6 + (heart - 85) / 24 + (ambient - 28) / 11 + (humidity - 55) / 100
    risk = np.where(heat_load > 2.1, "HIGH", np.where(heat_load > 0.05, "MODERATE", "LOW"))
    raw = np.column_stack([body, heart, ambient, humidity])
    x = np.asarray([normalize_features(row.tolist()) for row in raw])
    x_train, x_test, y_train, y_test = train_test_split(x, risk, test_size=.2, random_state=42, stratify=risk)
    model = RandomForestClassifier(n_estimators=160, max_depth=12, min_samples_leaf=2, class_weight="balanced", random_state=42, n_jobs=-1)
    model.fit(x_train, y_train)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"version": MODEL_VERSION, "model": model}, path)
    predicted = model.predict(x_test)
    metrics = {"accuracy": round(accuracy_score(y_test, predicted), 4),
        "precision_macro": round(precision_score(y_test, predicted, average="macro", zero_division=0), 4),
        "recall_macro": round(recall_score(y_test, predicted, average="macro", zero_division=0), 4),
        "f1_macro": round(f1_score(y_test, predicted, average="macro"), 4),
        "confusion_matrix": confusion_matrix(y_test, predicted, labels=LABELS).tolist(),
        "labels": LABELS, "training_rows": int(len(x_train)), "test_rows": int(len(x_test)),
        "evaluation_source": "Deterministic synthetic demonstration dataset; held-out test split",
        "model_version": MODEL_VERSION}
    path.with_suffix(".metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics


class Predictor:
    def __init__(self, path: Path):
        artifact = joblib.load(path) if path.exists() else None
        if not isinstance(artifact, dict) or artifact.get("version") != MODEL_VERSION:
            train_model(path)
            artifact = joblib.load(path)
        self.model = artifact["model"]
        self.version = artifact["version"]
        metrics_path = path.with_suffix(".metrics.json")
        if not metrics_path.exists():
            train_model(path)
        self.metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

    def predict(self, features: list[float]) -> tuple[str, float]:
        if not all(0 <= value <= 1 for value in features):
            features = normalize_features(features)
        probabilities = self.model.predict_proba([features])[0]
        index = int(np.argmax(probabilities))
        return str(self.model.classes_[index]), float(probabilities[index])

