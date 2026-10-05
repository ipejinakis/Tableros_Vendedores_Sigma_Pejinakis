"""Cruza el reporte 'venta detallada' de SIGMA contra nuestros datos (API), por factura.

Uso: python scripts/analisis/comparar_reporte.py "../Compreahora venta detallada.xlsx" --vendedor 100 --hasta 2026-09-28
Imprime solo resúmenes (totales por proveedor y las facturas que difieren).
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from sigma_conn.config import load_settings  # noqa: E402
from sigma_conn.store import Store  # noqa: E402
from sigma_conn.transform import ventas_validas  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("reporte")
ap.add_argument("--vendedor", default="100")
ap.add_argument("--desde", default="2026-09-01")
ap.add_argument("--hasta", default="2026-09-28")
ap.add_argument("--top", type=int, default=15)
a = ap.parse_args()
pd.options.display.width = 250
pd.options.display.float_format = "{:,.2f}".format

rep = pd.read_excel(a.reporte, dtype={"Cuenta": str, "Comprobante": str, "Ven": str})
rep = rep[rep["Ven"].astype(str).str.strip().str.lstrip("0") == a.vendedor.lstrip("0")].copy()
rep = rep[(rep["Fecha"] >= a.desde) & (rep["Fecha"] <= a.hasta)]

cfg = load_settings()
st = Store(cfg.data_dir, cfg.store_format)
v = ventas_validas(st.read_facts("fact_ventas_item"))
v = v.merge(st.read_table("dim_articulo")[["articulo_id", "proveedor"]], on="articulo_id", how="left")
v = v[(v["vendedor_id"] == a.vendedor) & (v["fecha"] >= a.desde) & (v["fecha"] <= a.hasta)]

# ¿ffacnum del reporte == factura_id de la API?
ov = len(set(pd.to_numeric(rep["ffacnum"], errors="coerce").dropna().astype("int64")) & set(v["factura_id"].astype("int64")))
print(f"reporte: {len(rep)} filas | API: {len(v)} ítems | facturas en común (ffacnum=factura_id): {ov}")

for prov in sorted(rep["Proveedor"].dropna().unique()):
    r = rep[rep["Proveedor"] == prov].groupby("ffacnum")["Neto"].sum()
    o = v[v["proveedor"] == prov].groupby("factura_id")["importe_neto"].sum()
    r.index, o.index = r.index.astype("int64"), o.index.astype("int64")
    j = pd.concat([r.rename("reporte"), o.rename("api")], axis=1).fillna(0)
    j["dif"] = j["reporte"] - j["api"]
    d = j[j["dif"].abs() > 0.5].sort_values("dif")
    print(f"\n== {prov}: reporte {j['reporte'].sum():,.2f} | api {j['api'].sum():,.2f} | dif {j['dif'].sum():,.2f} "
          f"| facturas con diferencia: {len(d)} de {len(j)}")
    if len(d):
        print(d.head(a.top).to_string())
        if len(d) > a.top:
            print("...", len(d) - a.top, "más; las de mayor dif positiva:"); print(d.tail(5).to_string())
solo_api = v[~v["proveedor"].isin(rep["Proveedor"].unique())].groupby("proveedor")["importe_neto"].sum()
print("\nproveedores que están en la API y NO en el reporte:"); print(solo_api.to_string())
