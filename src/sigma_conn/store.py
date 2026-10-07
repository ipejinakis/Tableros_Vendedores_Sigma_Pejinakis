"""Almacenamiento en archivos (Parquet o CSV), con escritura atómica.

Layout (bajo SIGMA_DATA_DIR):
    silver/<tabla>.parquet                  dimensiones y snapshots (reemplazo completo)
    silver/<tabla>/YYYY-MM.parquet          hechos, particionados por mes de ``fecha``
    _meta/last_run.json                     resultado de la última corrida del ETL

Los hechos se actualizan con ``upsert_window``: se borra el rango [dde, hta] de cada mes
afectado y se insertan las filas nuevas. Así una ventana móvil recarga anulaciones/NC tardías
sin duplicar.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import pandas as pd

# Columnas que deben leerse siempre como texto (evita perder ceros a la izquierda al leer CSV).
TEXT_COLS = {
    "cliente_id", "vendedor_id", "articulo_id", "supervisor_id", "empresa", "sucursal",
    "rubro_cod", "linea_cod", "division_cod", "grupo_cod", "proveedor_cod",
    "comprobante_codigo", "comprobante_numero", "cliente_madre_id", "vendedor_predeterminado_id",
    "reparto_id",
}


def _month_range(dde: date, hta: date) -> list[str]:
    months, cur = [], date(dde.year, dde.month, 1)
    while cur <= hta:
        months.append(f"{cur.year:04d}-{cur.month:02d}")
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
    return months


class Store:
    def __init__(self, data_dir: Path, fmt: str = "parquet") -> None:
        if fmt not in {"parquet", "csv"}:
            raise ValueError(fmt)
        self.root = Path(data_dir)
        self.fmt = fmt
        self.silver = self.root / "silver"
        self.meta = self.root / "_meta"

    # ------------------------------------------------------------------ io básico
    @property
    def ext(self) -> str:
        return "parquet" if self.fmt == "parquet" else "csv"

    def _write(self, df: pd.DataFrame, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        os.close(fd)
        try:
            if self.fmt == "parquet":
                df.to_parquet(tmp, index=False)
            else:
                df.to_csv(tmp, index=False)
            os.replace(tmp, path)  # atómico: el tablero nunca lee un archivo a medias
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def _read(self, path: Path) -> pd.DataFrame:
        if self.fmt == "parquet":
            return pd.read_parquet(path)
        head = pd.read_csv(path, nrows=0).columns
        dtype = {c: "string" for c in head if c in TEXT_COLS}
        parse = [c for c in head if c == "fecha" or c.startswith("fecha_")]
        return pd.read_csv(path, dtype=dtype, parse_dates=parse)

    # ------------------------------------------------------------------ tablas completas
    def table_path(self, name: str) -> Path:
        return self.silver / f"{name}.{self.ext}"

    def write_table(self, name: str, df: pd.DataFrame) -> Path:
        path = self.table_path(name)
        self._write(df, path)
        return path

    def read_table(self, name: str) -> pd.DataFrame:
        path = self.table_path(name)
        if not path.exists():
            raise FileNotFoundError(f"No existe {path}. Correr el ETL primero.")
        return self._read(path)

    # ------------------------------------------------------------------ hechos por mes
    def fact_dir(self, name: str) -> Path:
        return self.silver / name

    def upsert_window(self, name: str, new: pd.DataFrame, dde: date, hta: date,
                      date_col: str = "fecha") -> int:
        """Reemplaza las filas con date_col en [dde, hta] por ``new``. Devuelve filas escritas."""
        lo, hi = pd.Timestamp(dde), pd.Timestamp(hta)
        if not new.empty:
            dates = pd.to_datetime(new[date_col])
            if ((dates < lo) | (dates > hi)).any():
                raise ValueError(f"{name}: hay filas fuera de la ventana {dde}..{hta}")
        written = 0
        for month in _month_range(dde, hta):
            path = self.fact_dir(name) / f"{month}.{self.ext}"
            if path.exists():
                old = self._read(path)
                keep = old[~pd.to_datetime(old[date_col]).between(lo, hi)]
            else:
                keep = pd.DataFrame(columns=new.columns)
            add = new[pd.to_datetime(new[date_col]).dt.strftime("%Y-%m") == month] if not new.empty else new
            parts = [p for p in (keep, add) if not p.empty]
            merged = pd.concat(parts, ignore_index=True) if parts else new.iloc[0:0]
            if merged.empty and not path.exists():
                continue
            self._write(merged.sort_values([date_col]).reset_index(drop=True), path)
            written += len(add)
        return written

    def read_facts(self, name: str, dde: date | None = None, hta: date | None = None,
                   date_col: str = "fecha") -> pd.DataFrame:
        folder = self.fact_dir(name)
        files = sorted(folder.glob(f"*.{self.ext}")) if folder.exists() else []
        if not files:
            raise FileNotFoundError(f"No hay datos de {name} en {folder}. Correr el ETL primero.")
        if dde or hta:  # leer solo los meses necesarios
            lo = dde or date(1900, 1, 1)
            hi = hta or date(2999, 12, 31)
            wanted = set(_month_range(lo, hi))
            files = [f for f in files if f.stem in wanted]
        df = pd.concat([self._read(f) for f in files], ignore_index=True) if files else pd.DataFrame()
        if not df.empty and (dde or hta):
            d = pd.to_datetime(df[date_col])
            if dde:
                df = df[d >= pd.Timestamp(dde)]
            if hta:
                df = df[d <= pd.Timestamp(hta)]
        return df.reset_index(drop=True)

    # ------------------------------------------------------------------ metadatos
    def write_meta(self, payload: dict) -> None:
        self.meta.mkdir(parents=True, exist_ok=True)
        payload = {**payload, "written_at": datetime.now(ZoneInfo("America/Argentina/Salta")).isoformat(timespec="seconds")}   # hora de Salta aunque el servidor esté en UTC
        tmp = self.meta / "last_run.json.tmp"
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        os.replace(tmp, self.meta / "last_run.json")

    def read_meta(self) -> dict | None:
        p = self.meta / "last_run.json"
        return json.loads(p.read_text()) if p.exists() else None
