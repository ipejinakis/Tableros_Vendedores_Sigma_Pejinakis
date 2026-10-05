"""Carga los objetivos de Club Faro (Peñaflor) y los artículos de cada línea.

Regla: TODO dato sale de la base (SIGMA). De los Excel solo se toman los objetivos y la lista de artículos; los
vendedores se ubican por nombre contra `dim_vendedor` y todo lo que figure en un Excel y no esté en la base se AVISA
(no se inventa ni se asigna a otro vendedor).

Lee, desde la carpeta del proyecto (la de arriba del repo):
  - `Objetivos Club Faro Sept Oct 2026.xlsx`  -> tabla `obj_club_faro` (vendedor × línea → objetivo de clientes con compra)
  - `articulos_club_faro.xlsx`                -> tabla `cfg_club_faro_articulo` (artículos de cada línea; INCLUIR S/N,
                                                 vacío = cuenta mientras no se complete)
Después de editar cualquiera de los dos Excel, volver a correr este script.

Uso (desde la raíz del repo, venv activo):
    python scripts/etl/cargar_club_faro.py
"""
import argparse
import sys
import warnings
from pathlib import Path

import openpyxl
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from sigma_conn import objetivos_excel as OX  # noqa: E402
from sigma_conn import tableros as TB  # noqa: E402
from sigma_conn import transform as T  # noqa: E402
from sigma_conn.config import load_settings  # noqa: E402
from sigma_conn.store import Store  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--objetivos", default=str(ROOT.parent / "Objetivos Club Faro Sept Oct 2026.xlsx"))
ap.add_argument("--articulos", default=str(ROOT.parent / "articulos_club_faro.xlsx"))
a = ap.parse_args()

warnings.filterwarnings("ignore", category=UserWarning)
settings = load_settings()
store = Store(settings.data_dir, settings.store_format)
dim_vend = store.read_table("dim_vendedor")

obj = OX.build_obj_club_faro(openpyxl.load_workbook(a.objetivos, data_only=True), dim_vendedor=dim_vend)
cfg = OX.build_cfg_club_faro_articulo(openpyxl.load_workbook(a.articulos, data_only=True))

pd.options.display.width = 220
pd.options.display.max_columns = 30
print("=== Vendedores del Excel de objetivos contra la base (dim_vendedor) ===")
cruce = obj.drop_duplicates("nombre_excel")[["nombre_excel", "vendedor_id", "nombre_base", "coincidencia"]]
print(cruce.to_string(index=False))
sin = obj[obj["coincidencia"] == "sin coincidencia"].drop_duplicates("nombre_excel")
if len(sin):
    print("\nAVISO: estos vendedores están en el Excel y NO en la base; quedan afuera del tablero hasta que se aclare:")
    for r in sin.itertuples():
        print(f"  - {r.nombre_excel} (lo más parecido en la base: {r.nombre_base or 'nada'})")
apr = obj[obj["coincidencia"] == "aproximada"].drop_duplicates("nombre_excel")
if len(apr):
    print("\nAVISO: cruce por nombre aproximado (revisar):", "; ".join(f"{r.nombre_excel} -> {r.vendedor_id} {r.nombre_base}" for r in apr.itertuples()))

# Vendedores que venden Peñaflor en la base y no tienen objetivo en el Excel (informativo)
try:
    meses = TB.meses_disponibles(store)[-2:]
    ventas = pd.concat([TB.cargar_ventas_mes(store, m) for m in meses], ignore_index=True)
    dim_art = store.read_table("dim_articulo")
    v = T.ventas_validas(ventas).merge(dim_art.drop_duplicates("articulo_id")[["articulo_id", "proveedor"]], on="articulo_id", how="left")
    pen = v[v["proveedor"].astype("string").str.upper().str.contains("PEÑAFLOR|PENAFLOR", na=False)]
    por_v = pen.groupby(pen["vendedor_id"].astype(str))["importe_neto"].sum()
    con_obj = set(obj.loc[obj["vendedor_id"] != "", "vendedor_id"])
    falta = por_v[~por_v.index.isin(con_obj) & (por_v.abs() > 1000)].sort_values(ascending=False)
    if len(falta):
        nom = dim_vend.drop_duplicates("vendedor_id").assign(vendedor_id=lambda d: d["vendedor_id"].astype(str)).set_index("vendedor_id")["nombre"]
        print(f"\nInfo: venden Peñaflor en la base ({', '.join(meses)}) y NO tienen objetivo de Club Faro en el Excel:")
        for vid, monto in falta.items():
            print(f"  - {vid} {nom.get(vid, '(no está en dim_vendedor)')}: {monto / 1e6:.2f} M$")
except Exception as exc:  # información accesoria: nunca debe frenar la carga
    print(f"\n(no se pudo cruzar con las ventas: {exc})")

try:
    dim_art = store.read_table("dim_articulo")
    ids = set(dim_art["articulo_id"].astype(str))
    faltan = cfg[~cfg["articulo_id"].isin(ids)]
    if len(faltan):
        print("\nAVISO: artículos del Excel que no existen en la base:\n", faltan[["linea", "articulo_id", "descripcion"]])
except FileNotFoundError:
    pass

store.write_table("obj_club_faro", obj[obj["vendedor_id"] != ""].reset_index(drop=True))
store.write_table("cfg_club_faro_articulo", cfg)

ok = obj[obj["vendedor_id"] != ""]
print(f"\nobj_club_faro: {len(ok)} filas, {ok['vendedor_id'].nunique()} vendedores")
print(ok.pivot_table(index=["vendedor_id", "nombre_base"], columns="linea", values="objetivo"))
print(f"\ncfg_club_faro_articulo: {len(cfg)} artículos")
print(cfg.groupby(["linea", "fuente"]).agg(articulos=("articulo_id", "count"), incluidos=("incluir", "sum")))
