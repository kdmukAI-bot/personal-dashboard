from pathlib import Path

from pydantic_settings import BaseSettings

_DEFAULT_DATA_DIR = Path.home() / ".local/share/personal-dashboard"
_DEFAULT_CORE_DB_PATH = _DEFAULT_DATA_DIR / "core.db"


class Settings(BaseSettings):
    core_database_url: str = f"sqlite+aiosqlite:///{_DEFAULT_CORE_DB_PATH}"

    # Bind to tailscale0 by running uvicorn with --host directly; default
    # loopback-only is the safe default.
    host: str = "127.0.0.1"
    port: int = 8421
    debug: bool = False

    notify_api_key: str = ""

    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = ""

    base_url: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def data_dir(self) -> Path:
        return _DEFAULT_DATA_DIR


settings = Settings()
