"""Configuración leída desde variables de entorno / archivo .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_BASE_URL = "https://sigma.sig2k.com/pejinakis@sigma/api/v10"


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "si", "sí", "s"}


@dataclass(frozen=True)
class Settings:
    base_url: str
    token: str
    data_dir: Path
    store_format: str  # "parquet" | "csv"
    window_days: int
    chunk_days: int
    min_interval_s: float
    timeout_s: int
    paginate: bool
    page_size: int

    def __repr__(self) -> str:  # nunca imprimir el token
        return (
            f"Settings(base_url={self.base_url!r}, token=<{'set' if self.token else 'vacío'}>, "
            f"data_dir={str(self.data_dir)!r}, store_format={self.store_format!r}, "
            f"window_days={self.window_days}, chunk_days={self.chunk_days})"
        )


def load_settings(env_file: str | Path | None = None) -> Settings:
    load_dotenv(env_file or ROOT / ".env")

    data_dir = Path(os.getenv("SIGMA_DATA_DIR", "./data"))
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir

    fmt = os.getenv("SIGMA_STORE_FORMAT", "parquet").strip().lower()
    if fmt not in {"parquet", "csv"}:
        raise ValueError(f"SIGMA_STORE_FORMAT inválido: {fmt!r} (usar parquet o csv)")

    return Settings(
        base_url=os.getenv("SIGMA_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        token=os.getenv("SIGMA_TOKEN", "").strip(),
        data_dir=data_dir,
        store_format=fmt,
        window_days=int(os.getenv("SIGMA_WINDOW_DAYS", "35")),
        chunk_days=int(os.getenv("SIGMA_CHUNK_DAYS", "90")),
        min_interval_s=float(os.getenv("SIGMA_MIN_INTERVAL_S", "1.0")),
        timeout_s=int(os.getenv("SIGMA_TIMEOUT_S", "180")),
        paginate=_bool(os.getenv("SIGMA_PAGINATE"), True),
        page_size=int(os.getenv("SIGMA_PAGE_SIZE", "200000")),
    )
