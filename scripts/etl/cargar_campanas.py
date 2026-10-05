"""Carga `cfg_campana_articulo` (artículos de cada campaña de Mis Ventas) desde el Excel de clasificación.

Lee `articulos_en_campana.xlsx` (carpeta del proyecto; hoja única) o, con --excel, otro archivo con el mismo formato
(CAMPAÑA, ARTICULO_ID, DESCRIPCION, INCLUIR). Mientras la columna INCLUIR esté vacía
el artículo cuenta como S (provisorio); lo que Juan marque S o N manda. Volver a correrlo después de editar el Excel.

Uso (desde la raíz del repo, venv activo):
    python scripts/etl/cargar_campanas.py
    python scripts/etl/cargar_campanas.py --excel "ruta/articulos_en_campana.xlsx"
"""
import argparse
import sys
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from sigma_conn import objetivos_excel as OX  # noqa: E402
from sigma_conn.config import load_settings  # noqa: E402
from sigma_conn.store import Store  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--excel", default=str(ROOT.parent / "articulos_en_campana.xlsx"))
a = ap.parse_args()

import openpyxl  # noqa: E402

warnings.filterwarnings("ignore", category=UserWarning)
wb = openpyxl.load_workbook(a.excel, data_only=True)
df = OX.build_cfg_campana_articulo(wb)
cfg = load_settings()
Store(cfg.data_dir, cfg.store_format).write_table("cfg_campana_articulo", df)

pd.options.display.width = 200
print(f"cfg_campana_articulo: {len(df)} filas")
print(df.groupby(["campana", "fuente"]).agg(articulos=("articulo_id", "count"), incluidos=("incluir", "sum")))
print("\nIncluidos aunque la sugerencia era N o ?:")
print(df[df["incluir"] & df["sugerencia"].isin(["N", "?"])].groupby(["campana", "sugerencia"]).size())
