"""Carga los objetivos y la configuración de negocio a tablas silver (no llama a la API).

Escribe en data/silver: obj_facturacion, obj_mix_marca, cfg_vendedor_perfil, cfg_supervisor_vendedor
(salen de sigma_conn/negocio.py) y obj_cobertura, obj_mis_ventas (salen del Excel de objetivos).

Uso (desde la raíz del repo, venv activo, requiere openpyxl):
    python scripts/etl/cargar_objetivos.py
    python scripts/etl/cargar_objetivos.py --excel "ruta/al/DATOS PARA REPORTE COMERCIAL.xlsx"
"""
import argparse
import sys
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from sigma_conn import objetivos as O  # noqa: E402
from sigma_conn import objetivos_excel as OX  # noqa: E402
from sigma_conn.config import load_settings  # noqa: E402
from sigma_conn.store import Store  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--excel", default=str(ROOT / "DATOS PARA REPORTE COMERCIAL.xlsx"))
a = ap.parse_args()

try:
    import openpyxl
except ImportError:
    sys.exit("Falta openpyxl: pip install openpyxl")

warnings.filterwarnings("ignore", category=UserWarning)  # imágenes wmf del Excel
wb = openpyxl.load_workbook(a.excel, data_only=True)

cfg = load_settings()
st = Store(cfg.data_dir, cfg.store_format)
tablas = {
    "obj_facturacion": O.build_obj_facturacion(),
    "obj_mix_marca": O.build_obj_mix_marca(),
    "cfg_vendedor_perfil": O.build_cfg_vendedor_perfil(),
    "cfg_supervisor_vendedor": O.build_cfg_supervisor_vendedor(),
    "obj_cobertura": OX.build_obj_cobertura(wb),
    "obj_mis_ventas": OX.build_obj_mis_ventas(wb),
}
for nombre, df in tablas.items():
    st.write_table(nombre, df)
    print(f"{nombre}: {len(df)} filas")

pd.options.display.width = 200
cob = tablas["obj_cobertura"]
print("\nCobertura: suma de objetivos por categoría (debe dar el total de la distribuidora):")
print(cob.groupby("categoria").agg(suma=("objetivo", "sum"), total_excel=("total_distribuidora", "first")).round(2))
mv = tablas["obj_mis_ventas"]
print("\nMis Ventas: filas por campaña y tipo:")
print(mv.groupby(["campana", "tipo"]).agg(vendedores=("vendedor_id", "nunique"), target_total=("target", "sum")))
print("\nVendedores con objetivo de Mis Ventas:", ", ".join(sorted(mv["vendedor_id"].unique())))
print("Vendedores con perfil de facturación:", ", ".join(tablas["cfg_vendedor_perfil"]["vendedor_id"]))

# Regla de datos: los vendedores salen de la base (dim_vendedor). Todo código de estas tablas que no esté (o esté
# desactivado) se avisa; no se corrige solo.
try:
    dim_v = st.read_table("dim_vendedor")
except Exception:
    dim_v = None
if dim_v is None or len(dim_v) == 0:
    print("\nAVISO: no hay dim_vendedor en la base; no se pudo chequear los vendedores (correr el ETL completo).")
else:
    fuera = OX.vendedores_fuera_de_la_base(tablas, dim_v)
    if fuera.empty:
        print("\nChequeo contra la base: todos los vendedores de las tablas existen y están activos en dim_vendedor.")
    else:
        print("\nAVISO: vendedores de los Excel / configuración que NO coinciden con la base (revisar):")
        print(fuera.to_string(index=False))
