"""Conexión a la API de SIGMA y ETL hacia archivos locales (Parquet/CSV)."""

from .client import SigmaClient, SigmaError, SigmaResponseTooLarge
from .config import Settings, load_settings

__all__ = ["SigmaClient", "SigmaError", "SigmaResponseTooLarge", "Settings", "load_settings"]
