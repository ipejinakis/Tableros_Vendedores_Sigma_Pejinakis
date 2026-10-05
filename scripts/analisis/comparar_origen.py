"""Compara las ventas de un vendedor/mes por origen y proveedor contra la captura de CRITERIOS.

Uso (desde la raíz del repo, con el venv activo, después de recargar ventas):
    python scripts/analisis/comparar_origen.py --vendedor 100 --mes 2026-09 --hasta 2026-09-29
"""
import argparse
import sys
from itertools import combinations
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from sigma_conn.config import load_settings  # noqa: E402
from sigma_conn.store import Store  # noqa: E402
from sigma_conn.transform import ventas_validas  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--vendedor", default="100")
ap.add_argument("--mes", default="2026-09")
ap.add_argument("--hasta", default=None)
ap.add_argument("--objetivo", type=float, default=102121526.73, help="neto de la captura")
ap.add_argument("--ccc", type=int, default=65, help="clientes con compra de la captura")
a = ap.parse_args()

cfg = load_settings()
st = Store(cfg.data_dir, cfg.store_format)
v = ventas_validas(st.read_facts("fact_ventas_item"))
art = st.read_table("dim_articulo")[["articulo_id", "proveedor"]]
v = v.merge(art, on="articulo_id", how="left")
v = v[(v["vendedor_id"] == a.vendedor) & (v["fecha"].dt.strftime("%Y-%m") == a.mes)]
if a.hasta:
    v = v[v["fecha"] <= pd.Timestamp(a.hasta)]
if "origen" not in v.columns:
    sys.exit("fact_ventas_item no tiene 'origen': recargá ventas con el ETL nuevo.")

pd.options.display.float_format = "{:,.2f}".format
pd.options.display.width = 200
print(f"\nVendedor {a.vendedor} · {a.mes} · hasta {a.hasta or 'fin de mes'} · ítems {len(v)}")
print("\n== Neto por origen ==")
print(v.groupby("origen").agg(neto=("importe_neto", "sum"), clientes=("cliente_id", "nunique"),
                              facturas=("factura_id", "nunique")))
print("\n== Neto por proveedor x origen ==")
print(v.pivot_table(index="proveedor", columns="origen", values="importe_neto", aggfunc="sum",
                    fill_value=0, margins=True))
print("\n== Combinaciones de origen vs captura ==")
origenes = sorted(v["origen"].dropna().unique())
rows = []
for n in range(1, len(origenes) + 1):
    for combo in combinations(origenes, n):
        s = v[v["origen"].isin(combo)]
        neto = s["importe_neto"].sum()
        rows.append(("+".join(combo), neto, neto - a.objetivo, s["cliente_id"].nunique(),
                     s["cliente_id"].nunique() - a.ccc))
print(pd.DataFrame(rows, columns=["origenes", "neto", "dif_vs_captura", "clientes", "dif_ccc"])
      .sort_values("dif_vs_captura", key=abs).to_string(index=False))
