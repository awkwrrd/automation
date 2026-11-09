"""Runtime configuration, read from environment variables (or a .env file)."""
import os
from pathlib import Path


def _load_dotenv() -> None:
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"):
        if candidate.is_file():
            for raw in candidate.read_text().splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
            return


_load_dotenv()


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


class Settings:
    def __init__(self) -> None:
        # Any SQLAlchemy URL works: sqlite, postgresql+psycopg, mysql+pymysql, mssql+pyodbc ...
        self.database_url: str = os.getenv("WMS_DATABASE_URL", "sqlite:///./wms.db")
        self.secret_key: str = os.getenv("WMS_SECRET_KEY", "dev-secret-change-me")
        self.token_ttl_hours: int = int(os.getenv("WMS_TOKEN_TTL_HOURS", "12"))
        self.admin_username: str = os.getenv("WMS_ADMIN_USERNAME", "admin")
        self.admin_password: str = os.getenv("WMS_ADMIN_PASSWORD", "admin")
        self.seed_demo_data: bool = _bool("WMS_SEED_DEMO_DATA", "true")
        self.cors_origins: list[str] = [
            o.strip() for o in os.getenv("WMS_CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
        ]
        self.app_name: str = os.getenv("WMS_APP_NAME", "Dockyard WMS")
        # Base URL external systems use to call back into this WMS (included in outbound payloads)
        self.public_url: str = os.getenv("WMS_PUBLIC_URL", "http://localhost:8000").rstrip("/")
        # Background delivery of outbound integration messages
        self.dispatcher_enabled: bool = _bool("WMS_DISPATCHER_ENABLED", "true")
        self.dispatch_interval: float = float(os.getenv("WMS_DISPATCH_INTERVAL_SECONDS", "2"))


settings = Settings()
