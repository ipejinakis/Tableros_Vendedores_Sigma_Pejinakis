"""Carga los artículos de cada línea de 11 Titulares (Peñaflor) a la base.

Regla: TODO dato sale de la base (SIGMA). Del Excel solo se toma la lista de artículos (hoja Articulos de
`articulos_11_titulares.xlsx`; INCLUIR vacío = cuenta mientras no se complete). Los objetivos (del distribuidor) están en
`negocio.py`. Después de editar el Excel, volver a correr este script.

Uso (desde la raíz del repo, venv activo):
    python scripts/etl/cargar_11_titulares.py
"""
import argparse
import sys
import warnings
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from sigma_conn import negocio as N  # noqa: E402
from sigma_conn import objetivos_excel as OX  # noqa: E402
from sigma_conn.config import load_settings  # noqa: E402
from sigma_conn.store import Store  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--articulos", default=str(ROOT.parent / "articulos_11_titulares.xlsx"))
a = ap.parse_args()

warnings.filterwarnings("ignore", category=UserWarning)
settings = load_settings()
store = Store(settings.data_dir, settings.store_format)
cfg = OX.build_cfg_11_titulares_articulo(openpyxl.load_workbook(a.articulos, data_only=True))

ids = set(store.read_table("dim_articulo")["articulo_id"].astype(str))
faltan = cfg[~cfg["articulo_id"].isin(ids)]
if len(faltan):
    print("AVISO: artículos del Excel que no existen en la base:\n", faltan[["linea", "articulo_id", "descripcion"]])
dup = cfg[cfg.duplicated("articulo_id", keep=False)].sort_values("articulo_id")
if len(dup):
    print("AVISO: artículos que están en más de una línea (cuentan en las dos):\n", dup[["linea", "articulo_id", "descripcion"]])

store.write_table("cfg_11_titulares_articulo", cfg)
print(f"\ncfg_11_titulares_articulo: {len(cfg)} artículos")
res = cfg.groupby("linea").agg(articulos=("articulo_id", "count"), incluidos=("incluir", "sum"))
res.index = [N.TITULARES_LINEAS[k]["nombre"] for k in res.index]
print(res)
print("\nPor defecto (INCLUIR vacío):", int((cfg["fuente"] == "por defecto (S)").sum()), "de", len(cfg))
