from pathlib import Path

from app.ml import train_model


if __name__ == "__main__":
    output = Path(__file__).resolve().parent / "data" / "random_forest.joblib"
    print(train_model(output))
    print(f"Saved model to {output}")
