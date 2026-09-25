from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://thermosense:thermosense@localhost:5432/thermosense"
    model_path: str = "data/random_forest.joblib"
    cors_origins: str = "http://localhost:5173"
    jwt_secret: str = "development-only-change-this-secret-before-deployment"
    jwt_expire_minutes: int = Field(default=720, ge=5, le=1440)
    admin_email: str = "admin@thermosense.local"
    admin_password: str = "ChangeMe-1234"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

