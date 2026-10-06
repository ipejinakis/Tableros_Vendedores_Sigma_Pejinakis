"""Valida los tableros contra el reporte "Informe de ventas" de SIGMA (Excel exportado de SIGMA ERP).

Compara, para las fechas del reporte: (A) neto total y por vendedor, (B) neto por vendedor y artículo, (C) rubro de cada
cliente (reporte vs dim_cliente) y (D) Club Faro (clientes con compra por vendedor y línea) calculado con los datos
del reporte y con la base, usando la MISMA función del tablero (`club_faro_compras`). Solo imprime resúmenes.

El reporte no trae el ID de artículo ni el estado (anulada): los artículos se cruzan por descripción y el reporte puede
incluir facturas anuladas que la base excluye (se muestran como diferencias para revisarlas).

Uso (desde la raíz del repo, venv activo):
    python scripts/analisis/validar_reporte_sigma.py "../ventas sigma 01 de octubre de 2026.xlsx"
    python scripts/analisis/validar_reporte_sigma.py "../reporte.xlsx" --top 30
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from sigma_conn import negocio as N  # noqa: E402
from sigma_conn import tableros as TB  # noqa: E402
from sigma_conn import transform as T  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("reporte")
ap.add_argument("--top", type=int, default=15)
a = ap.parse_args()
pd.options.display.width = 250
pd.options.display.max_colwidth = 45
pd.options.display.float_format = "{:,.2f}".format

rep = pd.read_excel(a.reporte, header=1, dtype={"Cuenta": str, "Código": str})
rep = rep[rep["Fecha"].notna() & rep["Neto"].notna()].copy()
rep["vendedor_id"] = rep["Código"].astype(str).str.strip().str.lstrip("0")
rep["cliente_id"] = rep["Cuenta"].astype(str).str.strip()
rep["desc"] = rep["Descripción"].astype(str).str.strip()
desde, hasta = rep["Fecha"].min().date(), rep["Fecha"].max().date()
print(f"Reporte: {len(rep)} líneas, {desde} a {hasta}, neto {rep['Neto'].sum():,.2f}, vendedores {rep['vendedor_id'].nunique()}")

store = TB.abrir_store()
ven = store.read_facts("fact_ventas_item", desde, hasta)
dim_art, dim_cli = store.read_table("dim_articulo"), store.read_table("dim_cliente")
dim_vend = store.read_table("dim_vendedor")
db = T.ventas_validas(ven).copy()
db["vendedor_id"] = db["vendedor_id"].astype(str)
db["cliente_id"] = db["cliente_id"].astype(str)
db["desc"] = db["articulo_desc"].astype(str).str.strip()
print(f"Base: {len(db)} ítems válidos (sin anuladas), neto {db['importe_neto'].sum():,.2f}")

# ------------------------------------------------------------------ A) totales y por vendedor
nombres = dim_vend.drop_duplicates("vendedor_id").assign(vendedor_id=lambda d: d["vendedor_id"].astype(str)).set_index("vendedor_id")["nombre"]
A = pd.concat([rep.groupby("vendedor_id")["Neto"].sum().rename("reporte"),
               db.groupby("vendedor_id")["importe_neto"].sum().rename("base")], axis=1).fillna(0)
A["dif"] = A["reporte"] - A["base"]
A.insert(0, "vendedor", A.index.map(nombres))
print("\n== A) Neto por vendedor (reporte vs base) ==")
print(A.sort_values("dif", key=abs, ascending=False).head(a.top).to_string())
print(f"TOTAL reporte {A['reporte'].sum():,.2f} | base {A['base'].sum():,.2f} | dif {A['dif'].sum():,.2f}")

# ------------------------------------------------------------------ B) vendedor x artículo
B = pd.concat([rep.groupby(["vendedor_id", "desc"])["Neto"].sum().rename("reporte"),
               db.groupby(["vendedor_id", "desc"])["importe_neto"].sum().rename("base")], axis=1).fillna(0)
B["dif"] = B["reporte"] - B["base"]
Bd = B[B["dif"].abs() > 0.5].sort_values("dif", key=abs, ascending=False)
print(f"\n== B) Neto por vendedor y artículo: {len(Bd)} combinaciones con diferencia de {len(B)} ==")
if len(Bd):
    print(Bd.head(a.top).to_string())

# ------------------------------------------------------------------ C) rubro del cliente
base_cli = dim_cli.drop_duplicates("cliente_id").assign(cliente_id=lambda d: d["cliente_id"].astype(str)).set_index("cliente_id")
rub = rep.drop_duplicates("cliente_id").set_index("cliente_id")["Rubro Descripción"].str.strip().str.upper()
rub_db = rub.index.map(base_cli["rubro"].astype(str).str.strip().str.upper())
C = pd.DataFrame({"rubro_reporte": rub, "rubro_base": rub_db}, index=rub.index)
Cd = C[(C["rubro_reporte"] != C["rubro_base"])]
print(f"\n== C) Rubro del cliente: {len(Cd)} de {len(C)} clientes difieren (reporte vs dim_cliente) ==")
if len(Cd):
    print(Cd.head(a.top).to_string())

# ------------------------------------------------------------------ D) Club Faro
try:
    cfg_cf = store.read_table("cfg_club_faro_articulo")
except FileNotFoundError:
    sys.exit("\nNo hay cfg_club_faro_articulo: correr scripts/etl/cargar_club_faro.py")
ids_por_desc = db.groupby("desc")["articulo_id"].agg(lambda s: sorted(set(map(str, s))))
art_desc = dim_art.drop_duplicates("articulo_id").assign(articulo_id=lambda d: d["articulo_id"].astype(str)) \
    .groupby(dim_art["descripcion"].astype(str).str.strip())["articulo_id"].agg(lambda s: sorted(set(s)))


def _id_de(desc: str):
    ids = ids_por_desc.get(desc) or art_desc.get(desc) or []
    return ids[0] if len(ids) == 1 else (None if not ids else ",".join(ids))


rep["articulo_id"] = rep["desc"].map(_id_de)
sin_id = rep[rep["articulo_id"].isna()]["desc"].unique()
amb = rep[rep["articulo_id"].astype(str).str.contains(",", na=False)]["desc"].unique()
print(f"\n== D) Club Faro ==\nDescripciones del reporte sin artículo en la base: {len(sin_id)} {list(sin_id)[:5]}")
if len(amb):
    print(f"Descripciones con más de un código en la base (se descartan del lado reporte): {list(amb)[:5]}")
rep_v = pd.DataFrame({"fecha": rep["Fecha"], "vendedor_id": rep["vendedor_id"], "cliente_id": rep["cliente_id"],
                      "articulo_id": rep["articulo_id"], "unidades": rep["Cantidad"], "es_nc": rep["Cantidad"] < 0,
                      "estado": "impaga", "importe_neto": rep["Neto"]}).dropna(subset=["articulo_id"])
rep_v = rep_v[~rep_v["articulo_id"].astype(str).str.contains(",")]
cr = TB.club_faro_compras(rep_v, dim_art, dim_cli, cfg_cf, desde, hasta)
cd = TB.club_faro_compras(ven, dim_art, dim_cli, cfg_cf, desde, hasta)


def _res(c: pd.DataFrame, col: str) -> pd.Series:
    out = {}
    for (vid, linea), g in c.groupby(["vendedor_id", "linea"]):
        out[(str(vid), linea)] = g["cliente_id"].nunique() if N.CLUB_FARO_LINEAS[linea]["modo"] == "clientes" else len(g)
    return pd.Series(out, name=col, dtype="float64")


D = pd.concat([_res(cr, "reporte"), _res(cd, "base")], axis=1).fillna(0)
if len(D):
    D["dif"] = D["reporte"] - D["base"]
    D.index.names = ["vendedor_id", "linea"]
    print("\nClub Faro, clientes (o pares cliente-SKU en blancos dulces) por vendedor y línea:")
    print(D.to_string())
    print(f"Diferencias: {int((D['dif'] != 0).sum())} de {len(D)} filas")
else:
    print("Ninguna compra de Club Faro en el reporte ni en la base para esas fechas.")
k = ["vendedor_id", "linea", "cliente_id", "articulo_id"]
m = cr.merge(cd, on=k, how="outer", indicator=True)
solo = m[m["_merge"] != "both"]
print(f"Compras (vendedor, línea, cliente, artículo) que están en un lado y no en el otro: {len(solo)}")
if len(solo):
    print(solo.assign(solo_en=solo["_merge"].map({"left_only": "reporte", "right_only": "base"})).drop(columns="_merge")
          .head(a.top * 2).to_string(index=False))
